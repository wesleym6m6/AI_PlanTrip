# SerpApi Google Flights 參數參考

engine: `google_flights` | 實測基準: TPE→DAD 2026-10-08~12 來回

## 參數表

**必填 + 必設：**

| param | type | default | values / format | notes |
|-------|------|---------|----------------|-------|
| `engine` | str | — | `"google_flights"` | 固定值 |
| `departure_id` | str | — | IATA `"TPE"` or kgmid `"/m/0fn2g"` | 逗號分隔多值 `"TPE,TSA"` |
| `arrival_id` | str | — | 同上 | 逗號分隔多值 `"DAD,HAN"` |
| `outbound_date` | str | — | `YYYY-MM-DD` | |
| `return_date` | str | — | `YYYY-MM-DD` | type=1 必填，type=2 不填 |
| `show_hidden` | bool | `false` | **始終設 `true`** | 8→104 筆，同額度不開會漏大量結果 |

**高頻使用：**

| param | type | default | values / format | notes |
|-------|------|---------|----------------|-------|
| `type` | int | `1` | 1=來回, 2=單程, 3=多城市 | 單程回傳更多(158 vs 104)；多城市需 `multi_city_json` |
| `adults` | int | `1` | 正整數 | |
| `currency` | str | `"USD"` | `"TWD"`, `"JPY"` | |
| `hl` | str | `"en"` | `"zh-TW"`, `"ja"` | 影響航空/機場名稱語言 |
| `gl` | str | `"us"` | `"tw"`, `"jp"` | 影響結果地域偏好 |
| `stops` | int | 不篩 | 0=不篩, 1=直飛, 2=≤1轉, 3=≤2轉 | ⚠️ **1=直飛（不是 0）** |
| `sort_by` | int | `1` | 1=最佳, 2=價格, 3=出發, 5=時長, 6=到達 | 只影響 other_flights |
| `max_price` | int | — | 幣別單位整數 | 嚴格遵守上限 |
| `include_airlines` | str | — | IATA 逗號分隔 `"VJ,IT"` | 不飛該航線回 0 筆；與 exclude 互斥 |
| `exclude_airlines` | str | — | IATA 逗號分隔 `"CI,BR"` | ⚠️ 不完全可靠，codeshare 仍出現 |
| `travel_class` | int | `1` | 1=經濟, 2=豪經, 3=商務, 4=頭等 | 高艙等選項少；頭等可能無結果 |

**乘客：**

| param | type | default | values / format | notes |
|-------|------|---------|----------------|-------|
| `children` | int | `0` | 正整數 | 2-11 歲；+1 child 價格約 ×2 |
| `infants_in_seat` | int | `0` | 正整數 | <2 歲佔位；含嬰兒座位費 |
| `infants_on_lap` | int | `0` | 正整數 | <2 歲不佔位；實測不加價 |

**進階篩選：**

| param | type | default | values / format | notes |
|-------|------|---------|----------------|-------|
| `max_duration` | int | — | 分鐘 | 含轉機等待 |
| `outbound_times` | str | — | `"start,end"` 24h 整數 `"6,12"` | 含 end 小時（6,12 = 06:00-12:59） |
| `return_times` | str | — | 同上 | 僅 type=1 有效 |
| `bags` | int | `0` | 0/1/2 | 託運行李件數 |
| `emissions` | int | — | `1`=低碳排 | 大幅縮減結果（104→3） |
| `layover_duration` | str | — | `"min,max"` 分鐘 `"60,300"` | 僅轉機航班生效 |
| `exclude_conns` | str | — | IATA 逗號分隔 `"HKG"` | 排除轉機機場，完全有效 |

**二階查詢（來回票 token）：**

| param | type | values / format | notes |
|-------|------|----------------|-------|
| `departure_token` | str | 從第 1 次搜尋結果取得 | 查該去程對應的回程航班；與 booking_token 互斥 |
| `booking_token` | str | 從第 2 次搜尋結果取得 | 查訂票連結（OTA 比價頁）；與 departure_token 互斥 |

## 來回票三階段流程（Two-stage round-trip flow）

來回票（`type=1`）的搜尋結果**只包含去程航班**。回程和訂票連結需要額外兩次搜尋，每次各消耗 1 次 SerpApi 額度（共 3 次完成一組來回選擇）。

```
第 1 次：初搜去程
  params: departure_id, arrival_id, outbound_date, return_date
  回傳:  best_flights[] + other_flights[]     ← 全部是去程
         每筆帶 departure_token

第 2 次：用 departure_token 查回程
  params: 同上 + departure_token=<使用者選定的去程 token>
  回傳:  best_flights[] + other_flights[]     ← 全部是該去程對應的回程
         每筆帶 booking_token
         price 變成去回合計總價

第 3 次（可選）：用 booking_token 查訂票連結
  params: 同上 + booking_token=<使用者選定的回程 token>
  回傳:  booking_options[]                    ← 各 OTA 訂票連結 + 價格
```

**注意：** 第 1 次回傳的 `price` 是去程 + Google 自動配對的最便宜回程的合計價，不是純去程價格。選不同回程後總價會變。

**不建議使用：**

| param | type | default | notes |
|-------|------|---------|-------|
| `deep_search` | bool | `false` | 慢 3 倍但結果差異極小 |

## 注意事項

1. **始終加 `show_hidden=true`** — 同額度從 ~8 筆增到 ~100 筆
2. **`stops` 語意反直覺** — 1=直飛，不是 0
3. **`exclude_airlines` 不嚴格** — codeshare 航班仍可能出現在轉機段
4. **來回票價 = 去程 + Google 自動配的最便宜回程**；選不同回程總價會變
5. **三步驟訂票**：搜尋 → `departure_token` 查回程 → `booking_token` 查訂票（各消耗 1 次額度）

## 回傳結構

```
best_flights[]               Google 推薦（不受 sort_by 影響）
other_flights[]              其他選項（受 sort_by 影響）
├── flights[]                每段航程
│   ├── departure_airport    {name, id, time}
│   ├── arrival_airport      {name, id, time}
│   ├── duration             分鐘
│   ├── airline / flight_number / airplane / travel_class / legroom
│   └── extensions[]         附加資訊（碳排、Wi-Fi 等）
├── layovers[]               轉機（直飛則無）{name, id, duration, overnight}
├── total_duration           總時長分鐘
├── price                    來回票價（數字）
├── carbon_emissions         {this_flight, typical_for_this_route, difference_percent}
├── departure_token          查回程用
└── booking_token            查訂票用（僅回程結果有）

price_insights               {lowest_price, typical_price_range[], price_level}
airports[]                   出發/到達機場資訊
```

## 實測摘要

| param | value | results | verified |
|-------|-------|---------|----------|
| baseline | — | 8 | ✅ |
| `show_hidden` | `true` | 104 | ✅ 8→104 |
| `stops` | `1` | 4 | ✅ 全直飛 |
| `stops` | `2` | 106 | ✅ 直飛+1轉 |
| `travel_class` | `2`/`3`/`4` | 4/81/0 | ✅ 頭等無結果 |
| `include_airlines` | `"VJ,IT"` | 1 | ✅ 僅 IT |
| `exclude_airlines` | `"CI,BR"` | 100 | ⚠️ 仍有 CI codeshare |
| `max_price` | `25000` | 103 | ✅ 最高 24,146 |
| `max_duration` | `300` | 4 | ✅ 最長 170min |
| `outbound_times` | `"6,12"` | 48 | ✅ 07:10~12:15 |
| `emissions` | `1` | 3 | ✅ 全低碳排 |
| `layover_duration` | `"60,300"` | 19 | ✅ |
| `exclude_conns` | `"HKG"` | 83 | ✅ 完全排除 |
| `children` | `1` | 24 | ✅ 含兒童票 |
| `infants_on_lap` | `1` | 27 | ✅ 不加價 |
| `departure_token` | token | 1 | ✅ 取得回程 |
| `booking_token` | token | 1 | ✅ 取得訂票連結 |
