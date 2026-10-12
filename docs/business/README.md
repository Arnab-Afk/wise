# Business plan (cfo.ai)

The plan is a live model in cfo.ai, built through the cfo.ai MCP server from Claude Code.
Read-only link (summary, assumptions, revenue, costs and cash): https://app.cfo.ai/s/cPgf01AUStZFzZd3

Horizon: launch in October 2026 (last close) to December 2028, monthly. Every number below is
calculated from the Assumptions page; change one there and the whole model updates.

## Pricing

- $30 per monitored service per month. A typical customer monitors 12 services, about $360 a month.
- Customers bring their own Anthropic key, so model usage is billed to them directly.
- Measured agent cost: **$0.11 per incident**, the median of 12 failure-injection runs
  ([evidence](../evidence/scenarios.md)), traced in neatlogs. At 2 incidents per service a month
  that is about $2.64 per customer per month, under 1% of what they pay us.

## Costs

| Cost | Driver | Assumption |
|---|---|---|
| Hosting | per monitored service | $2 / month |
| Payment fees | revenue | 3% |
| Founders | fixed | $6,000 / month combined |
| Engineers | 1 per 40 customers | $5,000 / month each |
| Tools and marketing | fixed | $2,100 / month |

Gross margin is about 90%.

## Results

| | Main | Downside |
|---|---|---|
| New customer growth / churn / price | 12% / 3% / $30 | 6% / 5% / $25 |
| Cash low point | $12.5K (Mar 2027) | $226 (Nov 2027) |
| Cash-flow positive from | Apr 2027 (dips $8 in Jun when the first engineer joins) | Dec 2027 |
| Customers, Dec 2027 | 97 | 53 |
| ARR, Dec 2027 | $418K | $190K |
| Customers, Dec 2028 | 418 | 125 |
| ARR, Dec 2028 | $1.8M | $449K |
| Cash, Dec 2028 | $559K | $87K |

Starting cash of $30,000 is an assumption. In the downside case it barely lasts, so a small raise
or lower marketing spend before mid-2027 is the decision that matters most.

All inputs except agent cost per incident are planning assumptions, not observed data.
