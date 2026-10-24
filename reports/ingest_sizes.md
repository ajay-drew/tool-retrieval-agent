# Tool definition sizes

Approximate tokens (JSON characters / 4) for each tool's input schema.

- Tools: 115
- All tools, untrimmed: 369,384
- All tools, trimmed: 57,435
- Over the 1,500-token limit after trimming: 11

  Reason: still over budget at the depth-2 floor; trimming deeper removes fields the call needs.

| Tool | Group | Untrimmed | Trimmed | Over budget |
|---|---|---:|---:|---|
| `orders_create` | checkout_orders_v2 | 64,330 | 4,926 | yes |
| `orders_confirm` | checkout_orders_v2 | 42,686 | 3,062 | yes |
| `orders_capture` | checkout_orders_v2 | 41,625 | 3,000 | yes |
| `orders_authorize` | checkout_orders_v2 | 41,435 | 2,762 | yes |
| `invoices_update` | invoicing_v2 | 18,013 | 2,341 | yes |
| `invoices_create` | invoicing_v2 | 17,877 | 2,210 | yes |
| `server_callback` | checkout_orders_v2 | 19,113 | 2,139 | yes |
| `setup-tokens_create` | vault_payment_tokens_v3 | 8,147 | 1,805 | yes |
| `templates_update` | invoicing_v2 | 13,643 | 1,626 | yes |
| `templates_create` | invoicing_v2 | 13,590 | 1,573 | yes |
| `partner-referrals_create` | customer_partner_referrals_v2 | 14,212 | 1,525 | yes |
| `subscriptions_create` | billing_subscriptions_v1 | 7,024 | 1,494 |  |
| `invoices_search-invoices` | invoicing_v2 | 2,639 | 1,485 |  |
| `invoices_payments` | invoicing_v2 | 2,250 | 1,391 |  |
| `subscriptions_revise` | billing_subscriptions_v1 | 4,191 | 1,346 |  |
| `authorizations_capture` | payments_payment_v2 | 2,018 | 1,259 |  |
| `find_eligible_methods` | payments_payment_v2 | 4,427 | 1,213 |  |
| `disputes_make-offer` | customer_disputes_v1 | 1,646 | 1,159 |  |
| `plans_create` | billing_subscriptions_v1 | 2,440 | 1,049 |  |
| `payment-tokens_create` | vault_payment_tokens_v3 | 1,314 | 1,006 |  |
| `captures_refund` | payments_payment_v2 | 1,687 | 904 |  |
| `payouts_post` | payments_payouts_batch_v1 | 2,096 | 882 |  |
| `trackers_put` | shipping_shipment_tracking_v1 | 4,203 | 842 |  |
| `orders_track_create` | checkout_orders_v2 | 5,613 | 835 |  |
| `search_get` | reporting_transactions_v1 | 1,894 | 751 |  |
| `web-profile_update` | payment-experience_web_experience_profiles_v1 | 1,224 | 707 |  |
| `web-profile_create` | payment-experience_web_experience_profiles_v1 | 1,186 | 669 |  |
| `disputes_list` | customer_disputes_v1 | 734 | 524 |  |
| `invoices_cancel` | invoicing_v2 | 674 | 521 |  |
| `invoices_send` | invoicing_v2 | 673 | 519 |  |
| `invoices_remind` | invoicing_v2 | 673 | 519 |  |
| `verify-webhook-signature_post` | notifications_webhooks_v1 | 1,059 | 460 |  |
| `invoices_refunds` | invoicing_v2 | 647 | 454 |  |
| `products_create` | catalogs_products_v1 | 3,098 | 402 |  |
| `orders_trackers_patch` | checkout_orders_v2 | 427 | 355 |  |
| `subscriptions_capture` | billing_subscriptions_v1 | 377 | 312 |  |
| `orders_patch` | checkout_orders_v2 | 384 | 311 |  |
| `authorizations_reauthorize` | payments_payment_v2 | 524 | 303 |  |
| `disputes_patch` | customer_disputes_v1 | 350 | 280 |  |
| `webhooks_update` | notifications_webhooks_v1 | 302 | 272 |  |
| `web-profile_partial-update` | payment-experience_web_experience_profiles_v1 | 293 | 263 |  |
| `products_patch` | catalogs_products_v1 | 292 | 262 |  |
| `plans_patch` | billing_subscriptions_v1 | 324 | 255 |  |
| `subscriptions_patch` | billing_subscriptions_v1 | 324 | 255 |  |
| `payouts_get` | payments_payouts_batch_v1 | 234 | 227 |  |
| `invoices_generate-qr-code` | invoicing_v2 | 225 | 218 |  |
| `invoices_list` | invoicing_v2 | 238 | 211 |  |
| `customer_payment-tokens_get` | vault_payment_tokens_v3 | 211 | 211 |  |
| `subscriptions_transactions` | billing_subscriptions_v1 | 208 | 208 |  |
| `webhooks_post` | notifications_webhooks_v1 | 695 | 198 |  |
| `plans_update-pricing-schemes` | billing_subscriptions_v1 | 1,178 | 190 |  |
| `webhooks-events_list` | notifications_webhooks_v1 | 267 | 184 |  |
| `disputes_require-evidence` | customer_disputes_v1 | 258 | 182 |  |
| `trackers-batch_post` | shipping_shipment_tracking_v1 | 4,493 | 181 |  |
| `trackers_post` | shipping_shipment_tracking_v1 | 4,493 | 181 |  |
| `simulate-event_post` | notifications_webhooks_v1 | 204 | 180 |  |
| `templates_list` | invoicing_v2 | 195 | 169 |  |
| `plans_list` | billing_subscriptions_v1 | 194 | 163 |  |
| `balances_get` | reporting_transactions_v1 | 168 | 159 |  |
| `disputes_adjudicate` | customer_disputes_v1 | 163 | 157 |  |
| `disputes_deny-offer` | customer_disputes_v1 | 160 | 152 |  |
| `disputes_accept-offer` | customer_disputes_v1 | 155 | 148 |  |
| `disputes_escalate` | customer_disputes_v1 | 155 | 147 |  |
| `trackers-batch_get` | shipping_shipment_tracking_v1 | 140 | 140 |  |
| `products_list` | catalogs_products_v1 | 172 | 139 |  |
| `webhooks-events_resend` | notifications_webhooks_v1 | 142 | 136 |  |
| `trackers_get` | shipping_shipment_tracking_v1 | 128 | 128 |  |
| `orders_get` | checkout_orders_v2 | 126 | 126 |  |
| `disputes_send-message` | customer_disputes_v1 | 114 | 114 |  |
| `subscriptions_activate` | billing_subscriptions_v1 | 123 | 113 |  |
| `subscriptions_cancel` | billing_subscriptions_v1 | 118 | 109 |  |
| `subscriptions_suspend` | billing_subscriptions_v1 | 116 | 108 |  |
| `invoices_payments-delete` | invoicing_v2 | 108 | 108 |  |
| `invoices_refunds-delete` | invoicing_v2 | 108 | 108 |  |
| `disputes_accept-claim` | customer_disputes_v1 | 104 | 104 |  |
| `disputes_acknowledge-return-item` | customer_disputes_v1 | 104 | 104 |  |
| `disputes_provide-supporting-info` | customer_disputes_v1 | 103 | 103 |  |
| `disputes_provide-evidence` | customer_disputes_v1 | 102 | 102 |  |
| `disputes_appeal` | customer_disputes_v1 | 102 | 102 |  |
| `subscriptions_get` | billing_subscriptions_v1 | 101 | 101 |  |
| `captures_get` | payments_payment_v2 | 75 | 75 |  |
| `authorizations_get` | payments_payment_v2 | 74 | 74 |  |
| `authorizations_void` | payments_payment_v2 | 74 | 74 |  |
| `refunds_get` | payments_payment_v2 | 72 | 72 |  |
| `disputes_get` | customer_disputes_v1 | 69 | 69 |  |
| `invoices_get` | invoicing_v2 | 64 | 64 |  |
| `invoices_delete` | invoicing_v2 | 64 | 64 |  |
| `payouts-item_get` | payments_payouts_batch_v1 | 64 | 64 |  |
| `payouts-item_cancel` | payments_payouts_batch_v1 | 64 | 64 |  |
| `templates_get` | invoicing_v2 | 63 | 63 |  |
| `templates_delete` | invoicing_v2 | 63 | 63 |  |
| `webhooks-events_get` | notifications_webhooks_v1 | 63 | 63 |  |
| `partner-referrals_read` | customer_partner_referrals_v2 | 61 | 61 |  |
| `webhooks_list` | notifications_webhooks_v1 | 61 | 61 |  |
| `invoicing_generate-next-invoice-number` | invoicing_v2 | 62 | 57 |  |
| `invoice_connection_details_get` | invoicing_v2 | 57 | 57 |  |
| `payment-tokens_get` | vault_payment_tokens_v3 | 57 | 57 |  |
| `payment-tokens_delete` | vault_payment_tokens_v3 | 57 | 57 |  |
| `setup-tokens_get` | vault_payment_tokens_v3 | 57 | 57 |  |
| `webhooks_get` | notifications_webhooks_v1 | 55 | 55 |  |
| `webhooks_delete` | notifications_webhooks_v1 | 55 | 55 |  |
| `event-types_list` | notifications_webhooks_v1 | 55 | 55 |  |
| `webhooks-lookup_get` | notifications_webhooks_v1 | 54 | 54 |  |
| `webhooks-lookup_delete` | notifications_webhooks_v1 | 54 | 54 |  |
| `products_get` | catalogs_products_v1 | 45 | 45 |  |
| `web-profile_get` | payment-experience_web_experience_profiles_v1 | 45 | 45 |  |
| `web-profile_delete` | payment-experience_web_experience_profiles_v1 | 45 | 45 |  |
| `plans_get` | billing_subscriptions_v1 | 44 | 44 |  |
| `plans_activate` | billing_subscriptions_v1 | 44 | 44 |  |
| `plans_deactivate` | billing_subscriptions_v1 | 44 | 44 |  |
| `connections_get` | invoicing_v2 | 8 | 8 |  |
| `webhooks-lookup_list` | notifications_webhooks_v1 | 8 | 8 |  |
| `webhooks-lookup_post` | notifications_webhooks_v1 | 8 | 8 |  |
| `webhooks-event-types_list` | notifications_webhooks_v1 | 8 | 8 |  |
| `web-profile_get-list` | payment-experience_web_experience_profiles_v1 | 8 | 8 |  |
