# Taxonomy

The versioned source of truth is `guardian_voc/taxonomy/voc_v1.yaml`. It defines
one primary topic per item across product quality/authenticity, price/promotion,
availability/assortment, delivery/fulfilment, checkout/payment, store/staff,
customer service, returns/refunds, loyalty/membership, and other. Intent is one
of complaint, praise, question/request, suggestion, or purchase consideration.

The classifier must return an exact evidence substring, a confidence score, and
version metadata. Public social attribution requires an exact brand-evidence
substring; otherwise the record is retained as ambiguous evidence.

