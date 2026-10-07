# Vision model evaluation set

A labelled set to measure the photo vision model's accuracy honestly (relevance
detection, AI-generated detection, tag recall). Until it holds real, human-labelled
examples, `scripts/eval_vision.py` reports zero rather than a fabricated number —
model accuracy is a roadmap item, not a measured claim.

## How to populate

1. Drop real photos into `data/eval/images/` (a mix: genuine river/stream photos,
   off-topic photos e.g. a room or laptop, and known AI-generated images).
2. Label each in `manifest.json` under `cases`:

   ```json
   {
     "image": "yarra-clear-01.jpg",
     "is_relevant": true,
     "is_ai_generated": false,
     "expected_tags": ["river", "vegetation"]
   }
   ```

   - `is_relevant` (required): is this genuinely an in-focus river/stream photo?
   - `is_ai_generated` (optional): true for known synthetic images.
   - `expected_tags` (optional): tags you'd expect; scored by loose recall.

3. Run the harness:

   ```bash
   uv run python scripts/eval_vision.py
   ```

   It uses the configured provider (real Foundry model if `FOUNDRY_*` is set,
   else the heuristic) and prints per-dimension accuracy with sample sizes.

Images here are git-ignored (`images/`) so real/large/licensed photos are never
committed — keep the labelled set in your own evaluation store.
