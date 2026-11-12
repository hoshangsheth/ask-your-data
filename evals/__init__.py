"""
Evaluation of the text-to-SQL agent against hand-written reference SQL.

    questions.jsonl   31 questions with PostgreSQL reference SQL (2 deliberately unanswerable)
    dataset.py        load questions; get reference SQL for a dialect
    scoring.py        compare result sets (execution accuracy)
    run_eval.py       run the agent on every question and write evals/results.json

Run (calls the real AI provider, so it costs a little):
    python -m evals.run_eval
"""
