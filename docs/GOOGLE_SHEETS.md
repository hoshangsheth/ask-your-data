# Feedback in a Google Sheet (optional, about 5 minutes)

Every 👍 / 👎 is always stored in the database, and admins can download all of it as Excel from
the Metrics page (**Download all feedback (Excel)**, or `GET /api/metrics/feedback.xlsx`).

If you would rather watch feedback arrive live in a Google Sheet, set up this small Apps Script
once. Each rating is then appended as a new row with: time, rating, note, name, company, email,
question, how it was understood, answer, SQL, dataset, model, answer time and question id.

Until `FEEDBACK_SHEET_URL` is set, the sync is off. If the sheet is ever unreachable the user's
click still succeeds; the failure is only logged (`feedback_sheet_failed`).

## 1. Create the sheet and the script

1. Create a new Google Sheet (for example "Ask Your Data feedback").
2. **Extensions → Apps Script**. Replace the contents of `Code.gs` with:

```javascript
// Pick any long random string; the same value goes in FEEDBACK_SHEET_TOKEN.
const TOKEN = "paste-a-long-random-string-here";

function doPost(e) {
  const body = JSON.parse(e.postData.contents);
  if (body.token !== TOKEN) {
    return ContentService.createTextOutput("forbidden");
  }
  const lock = LockService.getScriptLock();
  lock.waitLock(10000); // two ratings at once never overwrite each other
  try {
    const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];
    if (sheet.getLastRow() === 0) {
      sheet.appendRow(body.columns);
      sheet.getRange(1, 1, 1, body.columns.length).setFontWeight("bold");
      sheet.setFrozenRows(1);
    }
    sheet.appendRow(body.row);
  } finally {
    lock.releaseLock();
  }
  return ContentService.createTextOutput("ok");
}
```

3. Click **Save**.

## 2. Deploy it as a web app

1. **Deploy → New deployment**, then the gear icon → **Web app**.
2. **Execute as:** Me. **Who has access:** Anyone.
   (The app calls it from the server without a Google login; the token is what keeps others out.)
3. **Deploy**, approve the permission prompt (it only needs access to this sheet), and copy the
   **Web app URL** (it ends in `/exec`).

## 3. Tell the app about it

In Vercel → Project → Settings → Environment Variables (Production), add:

| Name | Value |
|---|---|
| `FEEDBACK_SHEET_URL` | the `/exec` URL from step 2 |
| `FEEDBACK_SHEET_TOKEN` | the same string as `TOKEN` in the script |

Redeploy (Deployments → ⋯ → Redeploy). Rate any answer in the app and a row appears in the sheet
within a few seconds.

Locally, put the same two lines in `.env`.

## Notes

- Only new ratings go to the sheet. For everything rated before you set it up, download the
  Excel file once and paste it in.
- Changing a rating adds another row (the sheet is a log); the Excel export always shows each
  answer's current rating.
- If you edit the script later, use **Deploy → Manage deployments → Edit → New version** so the
  URL stays the same.
