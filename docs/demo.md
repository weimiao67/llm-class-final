# Demo script

An 8–10 minute presentation with a live demo on the deployed app. Slides:
[slides/housing-analyst.pptx](slides/housing-analyst.pptx) (14 slides, speaker notes on each).
To use them in Google Slides, upload the file to Google Drive and choose **Open with → Google
Slides**. To rebuild the deck after changing the numbers or text:
`uv run --with python-pptx --with matplotlib python docs/slides/build_slides.py`.

| Part | Slides | Time |
|---|---|---:|
| Problem and approach | 1–4 | 2 min |
| Model, training data, sampling | 5–7 | 2 min |
| Results | 8–9 | 1.5 min |
| Deployment, then **live demo** | 10–11 | 3 min |
| One failure fixed, one not; lessons; future work | 12–14 | 1.5 min |

## 30 minutes before

The endpoint costs about $1.5/hour, so start it only for the rehearsal and the demo.

1. **Start the app instance:** EC2 console → `llm-final-app` → Instance state → Start. Copy the
   new **Public IPv4 DNS**; it changes on every start.
2. **Check your IP is allowed:** `curl -s https://checkip.amazonaws.com` on the presenting laptop.
   If it differs from the security group's two rules (TCP 8501 and 8000), edit them. A venue's
   network usually has a different address from home.
3. **Deploy the model** in Studio (about 10 minutes). The model is the data-v2 training job's
   output; `scripts/launch_train.py` printed its path, and it is also under
   `s3://sagemaker-us-east-2-<account>/final-wm-qwen-lora-data-v2/` (job
   `final-wm-qwen-lora-data-v2-2026-11-23-17-46-11-441`):

   ```bash
   python scripts/deploy_endpoint.py --name final-wm-qwen-lora \
     --model-data s3://sagemaker-us-east-2-<account>/final-wm-qwen-lora-data-v2/final-wm-qwen-lora-data-v2-2026-11-23-17-46-11-441/output/model.tar.gz \
     --fallback-instance-types ml.g6.2xlarge ml.g6e.xlarge
   ```

   Note which instance type it gets (SageMaker console → the endpoint → its configuration), in
   case someone asks: `ml.g5.2xlarge`, or a g6 / g6e fallback when g5 capacity is short.

4. **Check readiness** from the laptop: `curl -s http://<dns>:8000/ready` must say
   `"status":"ready"`. The UI's sidebar status turns green.
5. **Warm up:** ask one question in the UI (the first request after deploy is slower), then
   click **New conversation**.
6. **Prepare the curl step:** copy the API key (Parameter Store → `/llm-final/api-key` → Show
   decrypted value) into a terminal: `export KEY='…' DNS=…`.
7. Open the slides, the UI in a browser tab, the terminal, and the backup video, in that order.

## The live demo

Ask the questions in this order, in one conversation (question 3 is a follow-up to question 2).
For each, show the **AI response** tab first, then **Evidence & trace**.

| # | Ask | Expect | Point out |
|---|---|---|---|
| 1 | What was Mead, CO's highest ZHVI month in 2025? | High $579,788 in Jan 2025, low $560,499 in Dec 2025 | Evidence tab: the plan the model emitted (`extrema`), the SQL with bound parameters, the resolved city with its county |
| 2 | Rank Colorado cities by ZHVI growth in 2025 | 333 cities, Telluride first (+8.95%); warnings: 7 cities excluded, top 10 shown | `state_filter: CO`, not a guessed city list (the base model's main failure). **Queried data** tab: all 333 rows, **Download CSV** |
| 3 | What about rent growth for the same cities and year? | Rent ranking, 52 cities, Fruita first (+8.75%) | The follow-up kept the state and year from the conversation. Fewer cities have rent data, and the warning says which were excluded |
| 4 | How did home values change in Oakwood, OH since 2020? | Clarification listing Oakwood in Cuyahoga, Montgomery, and Paulding counties | The validator asks instead of guessing. **Stop here: don't reply with the county**; resolving a clarification is untested ([model.md](model.md)) |
| 5 | What will Denver rent be next year? | Out of scope: forecasts aren't offered; historical data is | A refusal with an alternative, not an invented forecast |
| 6 | What is ZORI and how is it smoothed? | Three-month moving average, seasonally adjusted, with source links | `search_knowledge` over the reviewed methodology notes; the sources are clickable |

Then the API directly (slide 11):

```bash
curl -s http://$DNS:8000/v1/ask -H "X-API-Key: $KEY" -H 'content-type: application/json' \
  -d '{"question": "Rank Colorado cities by ZHVI growth in 2025", "include_rows": false}' \
  | python3 -m json.tool | head -40
```

Point out `kind`, `answer_source: "model"`, the `plan`, `sql.params`, and the `trace`. Without the
key, the same request returns 401.

**The known miss (slide 12)**, optional and only if there's time: in a new conversation, ask
question 2, then just "What about rent?". The model answers *unsupported*. All 50 metric-switch
follow-ups in its training data follow a single-city question ([evaluation.md](evaluation.md),
"Found in the live demo").

## If something goes wrong

| Symptom | Do this |
|---|---|
| UI doesn't load | Your IP changed: fix the security group rules (30 seconds). Otherwise switch to the backup video. |
| Sidebar: "Model endpoint not deployed" or "Creating" | The endpoint isn't up yet. Show the slides while it finishes, or the backup video. |
| An answer takes more than ~10 s | The first request after a deploy is slow; ask again. |
| An answer is wrong | Say so and show the evidence tab: the plan shows what the model asked for. That is the point of the design. |

## Afterwards

```bash
python scripts/deploy_endpoint.py --delete --name final-wm-qwen-lora   # stops the $1.5/hour
```

Then stop (or, after the final demo, terminate) the instance in the EC2 console.

## Recording the backup video

Record the full live demo once at the rehearsal: QuickTime Player → File → New Screen Recording,
with the browser and terminal. Keep it under 4 minutes and have it open in a second window during
the talk.
