# AI Usage Log: HelpDesk AI

Portfolio requirement (Step 19): show **responsible** AI use, not dependence on it.
The first three columns record what the AI did. The last column records what was **checked**. Rows marked **TODO** are checks only you can do. Complete them, in your own words, before you submit.

| Date | Task | AI assistance | My verification / result |
|---|---|---|---|
| 2026-10-26 | Choose the Project 3 topic | Claude compared the options on the project list and recommended the AI-Assisted IT Help Desk because it matches the Full-Stack specialization and builds on Project 1. | Checked against the guideline's Step 14 and the project list. **TODO:** confirm this is the project you want to defend. |
| 2026-10-26 | Write the first version of the app (Flask routes, SQLite schema, Bootstrap pages, JavaScript) | Claude generated the code for `app.py`, `schema.sql`, `templates/`, `static/`. | Ran the app in a real browser (login, search, create with live triage, comment, status change, empty-form validation, phone width). Edit and delete are covered by automated tests only. **TODO:** click through edit and delete yourself. Ran 53 automated tests. **TODO:** read every file and be able to explain each route and each SQL statement. |
| 2026-10-26 | Design the triage rules | Claude proposed the keyword lists, the title-counts-double rule, and the priority rules. | Tested each rule with unit tests. Found one tie-break problem (a spam email filed under Account) and fixed it so Security wins ties. **TODO:** review the keyword lists for words your own school's tickets use, and add or remove some. |
| 2026-10-26 | Write the automated tests | Claude wrote the 53 tests. | All pass. Two failed on the first run: one was a real triage problem (above), one was a wrong test expectation (403 vs 405). **TODO:** break something on purpose and confirm a test fails. |
| 2026-10-26 | Security design | Claude added CSRF checks for the API, escaping of ticket text, parameterized SQL and security headers. | Tests cover missing CSRF token (403), SQL-injection text, stored `<script>` text, open-redirect and security headers. **TODO:** be ready to explain CSRF, XSS and SQL injection in the mock interview. |
| 2026-10-26 | Write README, deploy file and portfolio page | Claude drafted the README from the Project 1 template, `render.yaml` and the portfolio page. | **TODO:** deploy it yourself, fill in your live link, GitHub link and screenshots from your own machine. |

## What did AI help me accomplish?

_Write in your own words._ Example: it produced a working first version of a full-stack app much faster than writing everything alone, and a test suite that caught a real bug.

## What did I personally verify?

_Write in your own words._ Fill this in after you complete the TODO items above.

## What did I learn from using AI?

_Write in your own words._

## What limitations or errors did I discover in AI-generated work?

- The first triage version classified a spam/scam email as an Account problem because two categories scored the same and the tie-break order was arbitrary. A test found it.
- A generated test expected the wrong HTTP status code (405 instead of 403) because it forgot the CSRF check runs first.
- The AI could not deploy the project or take screenshots on your machine. Those parts need you.

_Add the ones you find yourself._
