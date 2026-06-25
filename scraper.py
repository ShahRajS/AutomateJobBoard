#!/usr/bin/env python3
import os
import sys
import json
import re
import logging
from datetime import datetime
import pytz
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials
from serpapi import GoogleSearch

# Configure logging
log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scraper.log')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout)
    ]
)

def load_config():
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
    if not os.path.exists(config_path):
        logging.error(f"Config file not found at {config_path}")
        sys.exit(1)
    try:
        with open(config_path, 'r') as f:
            return json.load(f), config_path
    except Exception as e:
        logging.error(f"Failed to parse config.json: {e}")
        sys.exit(1)

def parse_years_of_experience(text):
    text_lower = text.lower()
    # Match patterns like "3+ years", "3-5 years", "3 to 5 years", "3 yrs", "3+ yrs"
    pattern = r'\b(\d+)\s*(?:\+|-|to)?\s*(?:\d+)?\s*(?:years?|yrs?)\b'
    matches = re.finditer(pattern, text_lower)
    years = []
    for m in matches:
        digits = re.findall(r'\d+', m.group(0))
        if not digits:
            continue
            
        min_years = int(digits[0])
        
        # We only check details for matches that could exceed the limit (>= 3 years)
        if min_years >= 3:
            start = max(0, m.start() - 100)
            end = min(len(text_lower), m.end() + 100)
            context = text_lower[start:end]
            
            # Check context for general experience indicators
            exp_indicators = ['experience', 'exp', 'work', 'background', 'software', 'engineer', 'industry', 'coding', 'dev', 'min', 'req', 'least', 'relevant', 'role', 'job', 'position', 'candidate', 'history', 'professional']
            if any(ind in context for ind in exp_indicators):
                years.append(min_years)
    return years

def is_entry_level(title, description, config):
    # Normalize by replacing any non-alphanumeric character with a space
    def normalize(text):
        return re.sub(r'[^a-z0-9]', ' ', text.lower())
        
    title_norm = normalize(title)
    desc_lower = description.lower()
    
    # 1. Check title exclusions (e.g. Senior, Lead, Staff, Principal)
    for exclude in config["experience_filter"]["exclude_titles"]:
        exclude_norm = normalize(exclude).strip()
        if not exclude_norm:
            continue
        # Match word boundaries on the normalized text
        if re.search(r'\b' + re.escape(exclude_norm) + r'\b', title_norm):
            # Check if there is an allowed title overriding it (e.g., "junior" in "Junior Senior")
            is_overridden = False
            for allowed in config["experience_filter"]["allowed_titles"]:
                allowed_norm = normalize(allowed).strip()
                if allowed_norm and re.search(r'\b' + re.escape(allowed_norm) + r'\b', title_norm):
                    is_overridden = True
                    break
            if not is_overridden:
                return False, f"Title contains excluded keyword '{exclude}'"

    # 2. Check title inclusions (e.g. Junior, Intern, New Grad).
    # If matched, we can bypass description keyword checks or give it extra weight.
    is_explicit_entry = False
    for allowed in config["experience_filter"]["allowed_titles"]:
        allowed_norm = normalize(allowed).strip()
        if allowed_norm and re.search(r'\b' + re.escape(allowed_norm) + r'\b', title_norm):
            is_explicit_entry = True
            break
            
    # 3. Check description exclusions (explicit keywords like "5+ years", "3+ years")
    for keyword in config["experience_filter"]["exclude_description_keywords"]:
        if keyword in desc_lower:
            if not is_explicit_entry:
                return False, f"Description contains excluded keyword '{keyword}'"
                
    # 4. Extract and check years of experience from description
    years = parse_years_of_experience(description)
    if years:
        max_allowed = config["experience_filter"]["max_years"]
        high_years = [y for y in years if y > max_allowed]
        if high_years:
            if not is_explicit_entry:
                return False, f"Required years of experience ({max(high_years)}+ years) exceeds limit of {max_allowed} years"

    # 5. Check if the description actually mentions "agent" or "agentic" to confirm focus,
    # just in case search retrieval is a bit too broad (e.g., matching general AI engineering roles).
    agentic_keywords = ["agent", "agentic", "autonomy", "autonomous", "swarm", "crewai", "langgraph", "autogen", "semantic kernel"]
    if not any(kw in title_norm or kw in desc_lower for kw in agentic_keywords):
        return False, "Does not explicitly mention AI agents or agentic concepts in title or description"

    return True, "Entry level (Passed all checks)"

def authenticate_gspread(credentials_path):
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    if not os.path.exists(credentials_path):
        logging.error(f"Google Service Account credentials file not found at '{credentials_path}'.")
        logging.error("Please follow the setup instructions in README.md to download your service account JSON file.")
        sys.exit(1)
        
    try:
        creds = Credentials.from_service_account_file(credentials_path, scopes=scopes)
        gc = gspread.authorize(creds)
        return gc
    except Exception as e:
        logging.error(f"Failed to authenticate with Google: {e}")
        sys.exit(1)

def apply_status_validation(ws):
    try:
        from gspread.utils import ValidationConditionType
        ws.add_validation(
            'I2:I5000',
            ValidationConditionType.one_of_list,
            ['N/A', 'Applied', 'Interviewing', 'Accepted', 'Rejected'],
            showCustomUi=True,
            strict=True
        )
        logging.info("Status dropdown validation applied successfully to Column I.")
    except Exception as validation_error:
        logging.warning(f"Could not apply Status dropdown validation: {validation_error}")

def get_or_create_sheet(gc, config, config_path):
    spreadsheet_id = os.getenv("SPREADSHEET_ID") or config.get("spreadsheet_id")
    spreadsheet_name = os.getenv("SPREADSHEET_NAME") or config.get("spreadsheet_name", "Agentic AI Entry Jobs SF")
    user_email = os.getenv("USER_EMAIL") or config.get("user_email")
    
    sh = None
    created_new = False
    
    # Check if ID is default placeholder
    if not spreadsheet_id or spreadsheet_id == "YOUR_SPREADSHEET_ID_HERE":
        logging.info("Spreadsheet ID is not configured. Attempting to create a new spreadsheet...")
        try:
            sh = gc.create(spreadsheet_name)
            spreadsheet_id = sh.id
            created_new = True
            logging.info(f"Created new spreadsheet: '{spreadsheet_name}' (ID: {spreadsheet_id})")
            
            # Share with user if email is provided
            if user_email and user_email != "YOUR_EMAIL_HERE@example.com":
                logging.info(f"Sharing spreadsheet with '{user_email}' as writer...")
                sh.share(user_email, perm_type='user', role='writer')
                logging.info("Successfully shared spreadsheet.")
            else:
                # Get client email from credentials file to show user
                with open(os.getenv('GOOGLE_APPLICATION_CREDENTIALS', 'credentials.json'), 'r') as f:
                    creds_data = json.load(f)
                    client_email = creds_data.get("client_email")
                logging.warning("="*80)
                logging.warning("IMPORTANT ACTION REQUIRED:")
                logging.warning("A new spreadsheet was created, but we couldn't share it because user_email is not configured.")
                logging.warning(f"Please create a sheet manually and share it with: {client_email}")
                logging.warning("Or set your user_email in config.json and delete the spreadsheet_id to recreate it.")
                logging.warning("="*80)
                
            # Save new ID to config.json
            config["spreadsheet_id"] = spreadsheet_id
            with open(config_path, 'w') as f:
                json.dump(config, f, indent=2)
            logging.info(f"Updated config.json with the new spreadsheet ID.")
        except Exception as e:
            logging.error(f"Failed to auto-create spreadsheet: {e}")
            logging.error("Please create one manually, share it with your service account email, and put the ID in config.json.")
            sys.exit(1)
    else:
        try:
            sh = gc.open_by_key(spreadsheet_id)
            logging.info(f"Opened existing spreadsheet: '{sh.title}'")
        except Exception as e:
            logging.warning(f"Error opening spreadsheet by ID '{spreadsheet_id}': {e}")
            logging.info("Attempting to open by name...")
            try:
                sh = gc.open(spreadsheet_name)
                spreadsheet_id = sh.id
                config["spreadsheet_id"] = spreadsheet_id
                with open(config_path, 'w') as f:
                    json.dump(config, f, indent=2)
                logging.info(f"Opened by name and updated config.json with ID: {spreadsheet_id}")
            except Exception as e2:
                logging.error(f"Could not open spreadsheet by name: {e2}")
                try:
                    with open(os.getenv('GOOGLE_APPLICATION_CREDENTIALS', 'credentials.json'), 'r') as f:
                        creds_data = json.load(f)
                        client_email = creds_data.get("client_email")
                    logging.error(f"Ensure the spreadsheet exists and is shared with: {client_email}")
                except:
                    pass
                sys.exit(1)
                
    # Get the first worksheet
    try:
        ws = sh.get_worksheet(0)
    except Exception as e:
        logging.warning(f"No worksheet found, adding new one: {e}")
        ws = sh.add_worksheet(title="Jobs", rows="1000", cols="10")
        
    headers = [
        "Date Added (PT)", 
        "Job Title", 
        "Company", 
        "Location", 
        "Source / Via", 
        "Experience Filter Status", 
        "Job ID", 
        "Apply Link", 
        "Status",
        "Description Snippet"
    ]
    
    try:
        existing_headers = ws.row_values(1)
    except Exception as e:
        existing_headers = []
        
    if not existing_headers:
        logging.info("Sheet is empty. Formatting headers and setting styling...")
        ws.append_row(headers)
        # Apply nice styling: Bold headers, freeze row 1
        try:
            ws.format("A1:J1", {
                "textFormat": {"bold": True, "foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0}},
                "backgroundColor": {"red": 0.12, "green": 0.43, "blue": 0.73}, # Nice blue header
                "horizontalAlignment": "CENTER"
            })
            # Freeze the first row
            sh.batch_update({
                "requests": [
                    {
                        "updateSheetProperties": {
                            "properties": {
                                "sheetId": ws.id,
                                "gridProperties": {"frozenRowCount": 1}
                            },
                            "fields": "gridProperties.frozenRowCount"
                        }
                    }
                ]
            })
            logging.info("Header styling and freeze row applied successfully.")
            apply_status_validation(ws)
        except Exception as style_error:
            logging.warning(f"Could not apply advanced header styling: {style_error}")
    else:
        # Check if we need to insert the "Status" column (self-healing migration)
        has_status = False
        for h in existing_headers:
            if h.strip().lower() == "status":
                has_status = True
                break
                
        if not has_status:
            logging.info("Detected old spreadsheet format. Inserting 'Status' column...")
            try:
                insert_col_idx = 9 # Default: Col I
                for idx, h in enumerate(existing_headers):
                    if "apply link" in h.lower():
                        insert_col_idx = idx + 2 # Column index after Apply Link (1-based index)
                        break
                        
                logging.info(f"Inserting empty column for 'Status' at column index {insert_col_idx}...")
                ws.insert_cols(values=[[]], col=insert_col_idx)
                
                # Write the header 'Status' in row 1 of the new column
                ws.update_cell(1, insert_col_idx, "Status")
                
                # Set formatting for the new header row
                try:
                    ws.format("A1:J1", {
                        "textFormat": {"bold": True, "foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0}},
                        "backgroundColor": {"red": 0.12, "green": 0.43, "blue": 0.73},
                        "horizontalAlignment": "CENTER"
                    })
                except Exception as fmt_err:
                    logging.warning(f"Could not format header row after migration: {fmt_err}")
                
                # Update the cell values of existing rows for status to "N/A"
                all_vals = ws.get_all_values()
                row_count = len(all_vals)
                if row_count > 1:
                    logging.info(f"Setting default status 'N/A' for {row_count - 1} existing rows...")
                    col_letter = chr(64 + insert_col_idx) if insert_col_idx <= 26 else 'I'
                    range_name = f"{col_letter}2:{col_letter}{row_count}"
                    cells_to_update = [[ "N/A" ] for _ in range(2, row_count + 1)]
                    ws.update(range_name, cells_to_update)
                    
                logging.info("'Status' column inserted and populated successfully.")
                apply_status_validation(ws)
            except Exception as insert_error:
                logging.error(f"Failed to migrate spreadsheet to add 'Status' column: {insert_error}")
        
    return ws

def get_job_signature(title, company):
    # Normalize: lowercase and strip non-alphanumeric characters
    clean_title = re.sub(r'[^a-z0-9]', '', title.lower())
    clean_company = re.sub(r'[^a-z0-9]', '', company.lower())
    return f"{clean_title}_{clean_company}"

def get_existing_jobs_metadata(ws):
    try:
        all_rows = ws.get_all_values()
        if len(all_rows) <= 1:
            return set(), set()
        
        headers = all_rows[0]
        title_idx = -1
        company_idx = -1
        job_id_idx = -1
        
        for idx, h in enumerate(headers):
            h_lower = h.lower()
            if "job title" in h_lower:
                title_idx = idx
            elif "company" in h_lower:
                company_idx = idx
            elif "job id" in h_lower:
                job_id_idx = idx
                
        # Fallbacks if headers differ
        if title_idx == -1: title_idx = 1
        if company_idx == -1: company_idx = 2
        if job_id_idx == -1: job_id_idx = 6
        
        job_ids = set()
        signatures = set()
        
        for row in all_rows[1:]:
            # Extract job ID
            if len(row) > job_id_idx:
                job_id = row[job_id_idx].strip()
                if job_id:
                    job_ids.add(job_id)
            
            # Extract signature
            if len(row) > max(title_idx, company_idx):
                title = row[title_idx].strip()
                company = row[company_idx].strip()
                if title and company:
                    signatures.add(get_job_signature(title, company))
                    
        return job_ids, signatures
    except Exception as e:
        logging.error(f"Error reading existing job metadata: {e}")
        return set(), set()

def cleanup_old_jobs(sh, ws):
    try:
        all_rows = ws.get_all_values()
        if len(all_rows) <= 1:
            return
            
        pt_tz = pytz.timezone('America/Los_Angeles')
        now_pt = datetime.now(pt_tz)
        
        rows_to_delete = [] # list of 0-based indices for API
        
        for idx, row in enumerate(all_rows[1:], 1):
            if not row or not row[0]:
                continue
                
            date_str = row[0].strip()
            try:
                # Parse date (format: 2026-06-24 01:23 PM)
                job_date = datetime.strptime(date_str, '%Y-%m-%d %I:%M %p')
                # Make it timezone-aware in PT
                job_date = pt_tz.localize(job_date)
                
                # Check if it was added more than 14 days ago
                age = now_pt - job_date
                if age.days > 14:
                    rows_to_delete.append(idx)
            except Exception as parse_error:
                logging.warning(f"Could not parse date '{date_str}' in row {idx}: {parse_error}")
                
        if rows_to_delete:
            logging.info(f"Found {len(rows_to_delete)} jobs added more than 14 days ago. Deleting them...")
            # Sort in descending order to prevent index shifting during deletion
            requests = []
            for r_idx in sorted(rows_to_delete, reverse=True):
                requests.append({
                    "deleteDimension": {
                        "range": {
                            "sheetId": ws.id,
                            "dimension": "ROWS",
                            "startIndex": r_idx,
                            "endIndex": r_idx + 1
                        }
                    }
                })
            sh.batch_update({"requests": requests})
            logging.info("Old jobs cleaned up successfully.")
    except Exception as cleanup_error:
        logging.error(f"Error during cleanup of old jobs: {cleanup_error}")

def search_serpapi_jobs(query, location, api_key, max_pages=2):
    logging.info(f"Querying SerpAPI for: '{query}' in '{location}'...")
    
    all_jobs = []
    # Query up to max_pages
    for page in range(max_pages):
        start = page * 10
        params = {
            "engine": "google_jobs",
            "q": query,
            "location": location,
            "hl": "en",
            "gl": "us",
            "start": start,
            "api_key": api_key
        }
        
        try:
            search = GoogleSearch(params)
            results = search.get_dict()
        except Exception as e:
            logging.error(f"SerpAPI request error (page {page}): {e}")
            break
            
        if "error" in results:
            logging.error(f"SerpAPI returned error: {results['error']}")
            break
            
        jobs = results.get("jobs_results", [])
        if not jobs:
            logging.info(f"No more jobs returned on page {page} for '{query}'")
            break
            
        logging.info(f"Retrieved {len(jobs)} jobs from page {page}")
        all_jobs.extend(jobs)
        
        if len(jobs) < 10:
            break
            
    return all_jobs

def main():
    # Load configuration
    config, config_path = load_config()
    
    # Load env variables (.env)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    load_dotenv(os.path.join(script_dir, '.env'))
    
    serpapi_key = os.getenv("SERPAPI_API_KEY")
    if not serpapi_key or serpapi_key == "your_serpapi_api_key_here":
        logging.error("SERPAPI_API_KEY is not configured in .env file.")
        logging.error("Please add your key to .env as SERPAPI_API_KEY=your_key")
        sys.exit(1)
        
    dry_run = "--dry-run" in sys.argv or "-d" in sys.argv
    
    if not dry_run:
        credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", os.path.join(script_dir, "credentials.json"))
        # Set the credential path in env for safety
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path
        
        # Connect to Google Sheet
        logging.info("Connecting to Google Sheets...")
        gc = authenticate_gspread(credentials_path)
        ws = get_or_create_sheet(gc, config, config_path)
        
        # Clean up jobs added more than 14 days ago
        cleanup_old_jobs(ws.spreadsheet, ws)
        
        # Read existing Job IDs and signatures to prevent duplicates
        existing_ids, existing_signatures = get_existing_jobs_metadata(ws)
        logging.info(f"Found {len(existing_ids)} existing job IDs and {len(existing_signatures)} signatures in spreadsheet.")
    else:
        logging.info("Dry-run mode activated. Querying SerpAPI and filtering, but skipping Google Sheets write.")
        existing_ids = set()
        existing_signatures = set()
    
    # Execute searches
    new_jobs_to_add = []
    pt_tz = pytz.timezone('America/Los_Angeles')
    current_time_str = datetime.now(pt_tz).strftime('%Y-%m-%d %I:%M %p')
    
    # Keep track of unique job IDs in the current run
    seen_in_run = set()
    
    for query in config["search_queries"]:
        try:
            max_pages = config.get("max_pages_per_query", 2)
            jobs = search_serpapi_jobs(query, config["search_location"], serpapi_key, max_pages)
        except Exception as e:
            logging.error(f"Failed to query '{query}': {e}")
            continue
            
        for job in jobs:
            job_id = job.get("job_id")
            title = job.get("title", "")
            company = job.get("company_name", "")
            
            if not job_id:
                # If SerpAPI doesn't return job_id, construct one from title + company
                job_id = f"{title}_{company}".replace(" ", "_")
                
            sig = get_job_signature(title, company)
            
            if job_id in existing_ids or sig in existing_signatures or job_id in seen_in_run or sig in seen_in_run:
                # Duplicate, skip
                continue
                
            seen_in_run.add(job_id)
            seen_in_run.add(sig)
            
            location = job.get("location", "")
            via = job.get("via", "")
            description = job.get("description", "")
            
            # Exclusively keep jobs from priority/exclusive sources if configured
            priority_sources = config.get("priority_sources", [])
            if priority_sources:
                via_lower = via.lower()
                is_valid_source = False
                for source in priority_sources:
                    if source in via_lower:
                        is_valid_source = True
                        break
                if not is_valid_source:
                    logging.debug(f"FILTERED OUT: '{title}' from '{via}' - not in exclusive sources list")
                    continue
            
            # Exclusively keep jobs in the SF Bay Area or Remote/Anywhere
            bay_area_keywords = ["san francisco", "sf", "oakland", "san jose", "mountain view", "palo alto", "menlo park", "redwood city", "san mateo", "sunnyvale", "santa clara", "cupertino", "berkeley", "fremont", "ca", "california", "bay area", "remote", "anywhere"]
            loc_lower = location.lower()
            if not any(kw in loc_lower for kw in bay_area_keywords):
                logging.debug(f"FILTERED OUT: '{title}' in '{location}' - not in SF Bay Area or Remote")
                continue
            
            # Apply entry-level filter
            is_entry, reason = is_entry_level(title, description, config)
            
            if is_entry:
                # Extract first apply link if available
                apply_link = ""
                apply_options = job.get("apply_options", [])
                if apply_options and len(apply_options) > 0:
                    apply_link = apply_options[0].get("link", "")
                
                # If no direct apply link, fall back to share link
                if not apply_link:
                    apply_link = job.get("share_link", "")
                    
                snippet = description[:300] + ("..." if len(description) > 300 else "")
                
                new_jobs_to_add.append([
                    current_time_str,
                    title,
                    company,
                    location,
                    via,
                    reason,
                    job_id,
                    apply_link,
                    "N/A",  # Status default value
                    snippet
                ])
                logging.info(f"MATCH: '{title}' at '{company}' in '{location}' - Reason: {reason}")
            else:
                logging.debug(f"FILTERED OUT: '{title}' at '{company}' - Reason: {reason}")
                
    if new_jobs_to_add:
        if not dry_run:
            logging.info(f"Inserting {len(new_jobs_to_add)} new jobs at the top of the spreadsheet...")
            try:
                # Insert at row 2 (just below the headers) to keep newest jobs at the top
                ws.insert_rows(new_jobs_to_add, row=2, value_input_option="USER_ENTERED")
                logging.info("Spreadsheet updated successfully!")
            except Exception as e:
                logging.error(f"Failed to write to Google Sheets: {e}")
        else:
            logging.info("=" * 80)
            logging.info(f"DRY RUN COMPLETE: Found {len(new_jobs_to_add)} matching job listings:")
            for idx, job in enumerate(new_jobs_to_add, 1):
                logging.info(f"{idx}. {job[1]} at {job[2]} ({job[3]})")
                logging.info(f"   Apply Link: {job[7]}")
                logging.info(f"   Filter Status: {job[5]}")
                logging.info("-" * 40)
            logging.info("=" * 80)
    else:
        logging.info("No new matching job listings found in this run.")
        
    logging.info("Scraper execution completed.")

if __name__ == "__main__":
    main()
