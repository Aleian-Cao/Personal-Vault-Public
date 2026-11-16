# Deterministic search eval 20261114_065624 (Qwen OFF, synthetic, 507 entries)

| set | n (denominator) | correct | wrong_account | clarification | abstain | false_exact | numeric_viol | secret_leaks | p95 ms |
|---|---|---|---|---|---|---|---|---|---|
| original 138 (all) | 138 | 130 | 0 | 0 | 8 | 0 | 0 | 0 | 22.5 |
| original dev (86) | 86 | 80 | 0 | 0 | 6 | 0 | 0 | 0 | 22.3 |
| original held-out (52) | 52 | 50 | 0 | 0 | 2 | 0 | 0 | 0 | 21.8 |
| red-team round 1 (34) | 34 | 34 | 0 | 0 | 0 | 0 | 7 | 0 | 19.4 |
| red-team round 2 (24) | 24 | 24 | 0 | 0 | 0 | 0 | 2 | 0 | 20.8 |
| red-team round 3 (30) | 30 | 21 | 0 | 1 | 8 | 0 | 6 | 0 | 19.5 |
| red-team round 4 (21) | 21 | 20 | 0 | 0 | 1 | 0 | 3 | 0 | 23.8 |
| red-team round 6 (13) | 13 | 9 | 3 | 0 | 1 | 0 | 5 | 0 | 19.6 |
| red-team round 7 (13) | 13 | 1 | 10 | 0 | 2 | 0 | 7 | 0 | 17.5 |
| ALL (273) | 273 | 239 | 13 | 1 | 20 | 0 | 30 | 0 | 22.2 |

Outcomes are mutually exclusive and sum to n. `wrong_account` = the eval's own flag; `clarification` = not correct but asks the user to choose; `abstain` = no entry shown for a query whose gold was an entry/ambiguous set. Ground truth of the 138 original queries is unchanged.

## wrong_account cases (13)
- `R6-04` "1" gold={'type': 'none'} got ambiguous ['PSCAD Demo 1', 'ETAP Server 1']
- `R6-05` "1" gold={'type': 'none'} got ambiguous ['PSCAD Demo 1', 'ETAP Server 1']
- `R6-07` "zalo của anh Minh" gold={'type': 'none'} got suggested ['Zalo Demo']
- `R7-01` "etap trừ 1, 5" gold={'type': 'ambiguous', 'accounts': ['ETAP Server 11', 'ETAP Server 15', 'ETAP Server 51']} got ambiguous ['ETAP Server 15', 'ETAP Server 1']
- `R7-02` "etap trừ 1 và 5, 11" gold={'type': 'ambiguous', 'accounts': ['ETAP Server 15', 'ETAP Server 51']} got ambiguous ['ETAP Server 15', 'ETAP Server 5']
- `R7-03` "demo 3 trừ pscad, synthetic" gold={'type': 'entry', 'account': 'VPN Demo 3', 'name': 'vpn3'} got ambiguous ['PSCAD Demo 3', 'Synthetic Account 3']
- `R7-04` "facebook trừ shop, cá nhân" gold={'type': 'none'} got ambiguous ['Facebook — Demo Personal', 'Facebook — Demo Shop']
- `R7-05` "pscad trừ 1, 2, 3" gold={'type': 'ambiguous', 'accounts': ['PSCAD Demo 4', 'PSCAD Demo 5']} got ambiguous ['PSCAD Demo 1', 'PSCAD Demo 2']
- `R7-06` "pscad trừ 1 & 5" gold={'type': 'ambiguous', 'accounts': ['PSCAD Demo 2', 'PSCAD Demo 3', 'PSCAD Demo 4']} got ambiguous ['PSCAD Demo 1', 'PSCAD Demo 2']
- `R7-08` "facebook trừ cá nhân ạ" gold={'type': 'entry', 'account': 'Facebook — Demo Shop', 'name': 'demo.shop@example.invalid'} got ambiguous ['Facebook — Demo Personal', 'Facebook — Demo Shop']
- `R7-10` "pscad trừ 1, 2" gold={'type': 'ambiguous', 'accounts': ['PSCAD Demo 3', 'PSCAD Demo 4', 'PSCAD Demo 5']} got ambiguous ['PSCAD Demo 1', 'PSCAD Demo 2']
- `R7-11` "pscad trừ 3, trừ 4" gold={'type': 'ambiguous', 'accounts': ['PSCAD Demo 1', 'PSCAD Demo 2', 'PSCAD Demo 5']} got ambiguous ['PSCAD Demo 1', 'PSCAD Demo 2']
- `R7-12` "pscad trừ 1 2 3 4" gold={'type': 'entry', 'account': 'PSCAD Demo 5', 'name': 'pscad5'} got ambiguous ['PSCAD Demo 1', 'PSCAD Demo 2']

## Not correct but safe on the original 138 (8): abstain / clarification
- `E04-03` (dev, abstain) "cho mình hỏi tài khoản facebook bán hàng với" gold=Facebook — Demo Shop -> none []
- `E04-06` (dev, abstain) "tôi muốn đăng nhập vào máy pscad số 3 thì dùng tài khoản nào" gold=PSCAD Demo 3 -> none []
- `E04-07` (dev, abstain) "tài khoản mạng xã hội dùng để bán hàng online là gì" gold=Facebook — Demo Shop -> none []
- `E04-08` (dev, abstain) "cái wifi ở phòng họp tầng ba mật khẩu bao nhiêu nhỉ" gold=Wifi Phòng họp Tầng 3 -> none []
- `E04-10` (heldout, abstain) "cho mình hỏi đăng nhập vpn số 3 ở đâu vậy" gold=VPN Demo 3 -> none []
- `E04-11` (dev, abstain) "email của công ty mình để đăng ký phần mềm là gì" gold=Gmail Công ty -> none []
- `E04-17` (dev, abstain) "tôi cần tài khoản ngân hàng demo để chuyển khoản thử" gold=Ngân hàng Demo -> none []
- `E05-15` (heldout, abstain) "ừm cho mình xem cái thứ hai trong mấy cái pscad lúc nãy" gold=PSCAD Demo 2 -> none []