# Agentic AI Job Scraper & Google Sheet Sync

A automated Python script that queries Google Jobs via SerpAPI for entry-level Agentic AI roles in the San Francisco Bay Area, and updates a Google Sheet. It is configured to run three times a day (8:30 AM, 2:00 PM, and 7:00 PM Pacific Time).

---

## Prerequisites

1. **Python 3**: Make sure Python 3 and `pip` are installed on your Mac.
2. **SerpAPI Account**: Sign up at [serpapi.com](https://serpapi.com) and get an API key (a free tier is available).
3. **Google Cloud Service Account**:
   - Go to the [Google Cloud Console](https://console.cloud.google.com/).
   - Create a project.
   - Go to **APIs & Services > Library**, search for and enable **Google Sheets API** and **Google Drive API**.
   - Go to **IAM & Admin > Service Accounts**, create a Service Account, and create a key in **JSON** format.
   - Save this JSON key file as `credentials.json` in the root of this project folder.
   - Note down the service account's email address (e.g. `your-service-account@your-project.iam.gserviceaccount.com`).

---

## Installation & Setup

### 1. Clone/Navigate to the Directory
Navigate to the directory in your terminal:
```bash
cd /path/to/job-scraper-gsheet
```

### 2. Set Up Virtual Environment (Recommended)
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure the Environment
- Copy the template environment file:
  ```bash
  cp .env.example .env
  ```
- Edit `.env` and paste your SerpAPI key:
  ```env
  SERPAPI_API_KEY=your_actual_serpapi_api_key
  ```

### 4. Configure the Google Sheet
You have two options to hook up your spreadsheet:

#### Option A: Auto-Create (Recommended)
1. Open [config.json](config.json).
2. Set `"user_email"` to your personal Google email address.
3. Keep `"spreadsheet_id"` as `"YOUR_SPREADSHEET_ID_HERE"`.
4. Run the scraper once:
   ```bash
   python3 scraper.py
   ```
5. The script will automatically create a new spreadsheet named `Agentic AI Entry Jobs SF`, share it with your personal email, and update `config.json` with the new spreadsheet ID! Check your Google Sheets dashboard.

#### Option B: Manual Setup
1. Create a new Google Spreadsheet manually.
2. Share the spreadsheet with your service account's email address as an **Editor/Writer**.
3. Copy the Spreadsheet ID from the URL (the string between `/d/` and `/edit` in `https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit`).
4. Paste this ID into `config.json` as the value for `"spreadsheet_id"`.

---

## Running the Scraper

### Manual Execution
Run the script to fetch jobs immediately:
```bash
python3 scraper.py
```
Logs will print to the console and be written to `scraper.log`.

---

## Scheduling (3x Daily)

We use macOS `cron` to run the job 3x a day at **8:30 AM**, **2:00 PM**, and **7:00 PM PT**.

### Automate Schedule Setup
Run the helper setup script to automatically configure your crontab:
```bash
chmod +x setup_cron.sh
./setup_cron.sh
```

### Verify Scheduling
To see the configured cron jobs, run:
```bash
crontab -l
```
You should see:
```text
# Agentic AI Job Scraper Cron Schedule
30 8 * * * /path/to/job-scraper-gsheet/venv/bin/python /path/to/job-scraper-gsheet/scraper.py >> /path/to/job-scraper-gsheet/cron_output.log 2>&1
0 14 * * * /path/to/job-scraper-gsheet/venv/bin/python /path/to/job-scraper-gsheet/scraper.py >> /path/to/job-scraper-gsheet/cron_output.log 2>&1
0 19 * * * /path/to/job-scraper-gsheet/venv/bin/python /path/to/job-scraper-gsheet/scraper.py >> /path/to/job-scraper-gsheet/cron_output.log 2>&1
```

To remove or edit the schedules manually, you can run:
```bash
crontab -e
```

---

## Cloud Scheduling (Alternative: GitHub Actions)

If you don't want to keep your Mac awake, you can schedule the job completely in the cloud for free using GitHub Actions:

### 1. Initialize Git Repository
In your project directory, initialize git and prepare files (excluding credentials):
```bash
git init
echo "venv/" >> .gitignore
echo ".env" >> .gitignore
echo "credentials.json" >> .gitignore
echo "scraper.log" >> .gitignore
echo "cron_output.log" >> .gitignore
git add .
git commit -m "Initial commit of Agentic AI Job Scraper"
```

### 2. Create a Private GitHub Repository
- Go to GitHub and create a new **Private** repository (do not make it public to protect your configurations and spreadsheet settings).
- Follow the instructions on GitHub to push your local repository:
  ```bash
  git remote add origin git@github.com:YOUR_USERNAME/YOUR_REPO_NAME.git
  git branch -M main
  git push -u origin main
  ```

### 3. Add GitHub Repository Secrets
On your repository page, go to **Settings > Secrets and variables > Actions** and create two repository secrets:
1. `SERPAPI_API_KEY`: Paste your SerpAPI key (`b037...`).
2. `GOOGLE_APPLICATION_CREDENTIALS_JSON`: Open your local `credentials.json` and paste its **entire raw JSON content** as the value.

### 4. Ensure Spreadsheet ID is Committed
Because GitHub Actions runs on an ephemeral container, any auto-creation changes will not persist.
- Run the scraper once locally to create your sheet (Option A in "Configure the Google Sheet" above).
- Verify that [config.json](config.json) has your new `"spreadsheet_id"`.
- Commit and push that `config.json` file to GitHub:
  ```bash
  git add config.json
  git commit -m "Add active spreadsheet ID"
  git push origin main
  ```

The workflow is located in `.github/workflows/scrape_jobs.yml` and is configured to run at **8:30 AM**, **2:00 PM**, and **7:00 PM PT** daily. You can also trigger it manually at any time under the **Actions** tab on GitHub!

