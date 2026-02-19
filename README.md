# Telegram → Google Sheets Bot (Koyeb Deployment)

## Step 1: Setup Google Cloud
1. Create project at https://console.cloud.google.com
2. Enable Google Sheets API & Google Drive API
3. Create Service Account
4. Download credentials.json
5. Share your Google Sheet with service account email (Editor access)

## Step 2: Telegram Setup
1. Create bot via @BotFather
2. Disable privacy mode
3. Add bot to group as Admin

## Step 3: Deploy on Koyeb
1. Upload project to GitHub
2. Create new App in Koyeb
3. Connect GitHub repo
4. Set runtime to Python
5. Set port to 8000
6. Add environment variables:
   - BOT_TOKEN
   - SHEET_NAME
   - WEBHOOK_URL

## Step 4: Set Webhook

Open in browser:

https://api.telegram.org/botYOUR_BOT_TOKEN/setWebhook?url=https://your-app-name.koyeb.app/webhook

If response is {"ok":true} your bot is live.
