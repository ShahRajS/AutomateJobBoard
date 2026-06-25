#!/bin/bash
# Get the absolute path of this script's directory
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
SCRIPTPATH="$DIR/scraper.py"

# Ensure the Python script is executable
chmod +x "$SCRIPTPATH"

# Save current crontab if it exists
crontab -l > mycron 2>/dev/null || touch mycron

# Remove any existing jobs referencing scraper.py to avoid duplicates
grep -v "scraper.py" mycron > mycron_temp

# Append the new cron schedules
# macOS runs cron in local system time.
echo "# Agentic AI Job Scraper Cron Schedule" >> mycron_temp
echo "0 6 * * * $DIR/venv/bin/python $SCRIPTPATH >> $DIR/cron_output.log 2>&1" >> mycron_temp
echo "0 17 * * * $DIR/venv/bin/python $SCRIPTPATH >> $DIR/cron_output.log 2>&1" >> mycron_temp

# Load new crontab
crontab mycron_temp
rm mycron mycron_temp

echo "=========================================================================="
echo "Successfully configured macOS cron jobs!"
echo "The scraper will run 2x a day at:"
echo "  - 6:00 AM"
echo "  - 5:00 PM"
echo "(Cron executes using system local time, currently Pacific Time)"
echo ""
echo "Verify configuration with: crontab -l"
echo "Check cron logs at: $DIR/cron_output.log"
echo "=========================================================================="
