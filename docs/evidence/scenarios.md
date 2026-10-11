# Scenario results

| When | Scenario | Incident | Outcome | Detected | Recovered | Turns | Cost | Actions |
|---|---|---|---|---|---|---|---|---|
| Oct 09 15:56 | bad-config | #1 | resolved | 6.7s | 117.9s | 5 | $0.08 | rollback payments |
| Oct 09 15:58 | bank-outage | #2 | resolved | 3.0s | 88.7s | 5 | $0.09 | set_flag payments_use_backup |
| Oct 09 16:00 | repeat | #3 | resolved | 15.8s | 100.7s | 5 | $0.09 | rollback payments |
| Oct 09 16:03 | change-mid-incident | #4 | resolved | 89.7s | 207.9s | 5 | $0.09 | rollback payments |
| Oct 09 16:06 | change-mid-incident | #5 | resolved | 26.4s | 121.4s | 5 | $0.10 | rollback payments |
| Oct 09 16:08 | code-bug | #6 | resolved | 5.9s | 94.4s | 5 | $0.12 | rollback checkout |
| Oct 10 20:27 | code-bug | #7 | resolved | 6.3s | 128.0s | 6 | $0.12 | rollback checkout |
| Oct 10 20:31 | code-bug | #8 | resolved | 8.6s | 210.9s | 7 | $0.14 | rollback checkout, deploy_fix checkout |
| Oct 10 23:04 | bad-config | #51 | resolved | 4.9s | 86.1s | 5 | $0.11 | rollback payments |
| Oct 10 23:50 | bad-config | #52 | resolved | 7.3s | 97.2s | 5 | $0.11 | rollback payments |
| Oct 11 00:37 | code-bug | #53 | resolved | 7.7s | 196.3s | 7 | $0.15 | rollback checkout, deploy_fix checkout |
| Oct 11 23:08 | bad-config | #55 | resolved | 5.4s | 90.0s | 5 | $0.12 | rollback payments |
