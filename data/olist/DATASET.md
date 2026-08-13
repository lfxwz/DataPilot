# Olist Brazilian E-Commerce Public Dataset

DataPilot uses the original public Olist relational dataset rather than generated business data.

## Source

- Dataset: Brazilian E-Commerce Public Dataset by Olist
- Original publisher: Olist
- Kaggle handle: `olistbr/brazilian-ecommerce`
- Source URL: https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce
- Coverage: anonymized Brazilian marketplace orders from 2016 through 2018
- Scale: approximately 100,000 orders across nine related CSV tables

## License and redistribution

The original Kaggle dataset is listed under CC BY-NC-SA 4.0. DataPilot does not redistribute
the raw CSV files. Users download them directly from Kaggle and remain responsible for complying
with the dataset license and Kaggle terms. The DataPilot source-code license does not replace or
override the dataset license.

When publishing results, attribute Olist and link to the original Kaggle dataset. Do not present
the anonymized historical data as current production data.

## Expected source files

```text
olist_customers_dataset.csv
olist_geolocation_dataset.csv
olist_order_items_dataset.csv
olist_order_payments_dataset.csv
olist_order_reviews_dataset.csv
olist_orders_dataset.csv
olist_products_dataset.csv
olist_sellers_dataset.csv
product_category_name_translation.csv
```

Raw files belong under `data/raw/olist/`, which is excluded from Git.

## Reproducibility

The downloader writes a local `manifest.json` containing the dataset handle and SHA-256 digest
of every downloaded CSV. The loader validates exact CSV headers before modifying PostgreSQL and
loads all tables inside one transaction.

