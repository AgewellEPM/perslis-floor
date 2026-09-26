# Demo

Fictional invoices and vendors, plus six tools that Perslis admitted,
reviewed against independently computed answers, and signed.

    python3 floor-serve.py --data demo/data --tools demo/tools --check

Then connect it to Claude Code and ask one of the questions:

    claude mcp add perslis-floor-demo -- python3 "$PWD/floor-serve.py" \
        --data "$PWD/demo/data" --tools "$PWD/demo/tools"
