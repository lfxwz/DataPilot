REVOKE CREATE ON SCHEMA public FROM PUBLIC;

CREATE SCHEMA olist AUTHORIZATION analytics_owner;

CREATE TABLE olist.product_category_translation (
    product_category_name text PRIMARY KEY,
    product_category_name_english text NOT NULL
);

CREATE TABLE olist.customers (
    customer_id text PRIMARY KEY,
    customer_unique_id text NOT NULL,
    customer_zip_code_prefix integer,
    customer_city text,
    customer_state text
);

CREATE TABLE olist.geolocation (
    geolocation_zip_code_prefix integer,
    geolocation_lat double precision,
    geolocation_lng double precision,
    geolocation_city text,
    geolocation_state text
);

CREATE TABLE olist.sellers (
    seller_id text PRIMARY KEY,
    seller_zip_code_prefix integer,
    seller_city text,
    seller_state text
);

CREATE TABLE olist.products (
    product_id text PRIMARY KEY,
    product_category_name text,
    product_name_length integer,
    product_description_length integer,
    product_photos_qty integer,
    product_weight_g numeric,
    product_length_cm numeric,
    product_height_cm numeric,
    product_width_cm numeric
);

CREATE TABLE olist.orders (
    order_id text PRIMARY KEY,
    customer_id text NOT NULL REFERENCES olist.customers(customer_id),
    order_status text NOT NULL,
    order_purchase_timestamp timestamp,
    order_approved_at timestamp,
    order_delivered_carrier_date timestamp,
    order_delivered_customer_date timestamp,
    order_estimated_delivery_date timestamp
);

CREATE TABLE olist.order_items (
    order_id text NOT NULL REFERENCES olist.orders(order_id),
    order_item_id integer NOT NULL,
    product_id text REFERENCES olist.products(product_id),
    seller_id text REFERENCES olist.sellers(seller_id),
    shipping_limit_date timestamp,
    price numeric(14, 2),
    freight_value numeric(14, 2),
    PRIMARY KEY (order_id, order_item_id)
);

CREATE TABLE olist.order_payments (
    order_id text NOT NULL REFERENCES olist.orders(order_id),
    payment_sequential integer NOT NULL,
    payment_type text,
    payment_installments integer,
    payment_value numeric(14, 2),
    PRIMARY KEY (order_id, payment_sequential)
);

CREATE TABLE olist.order_reviews (
    review_id text,
    order_id text REFERENCES olist.orders(order_id),
    review_score integer CHECK (review_score BETWEEN 1 AND 5),
    review_comment_title text,
    review_comment_message text,
    review_creation_date timestamp,
    review_answer_timestamp timestamp
);

CREATE INDEX customers_unique_id_idx ON olist.customers(customer_unique_id);
CREATE INDEX customers_state_idx ON olist.customers(customer_state);
CREATE INDEX geolocation_zip_idx ON olist.geolocation(geolocation_zip_code_prefix);
CREATE INDEX orders_customer_idx ON olist.orders(customer_id);
CREATE INDEX orders_purchase_timestamp_idx ON olist.orders(order_purchase_timestamp);
CREATE INDEX order_items_product_idx ON olist.order_items(product_id);
CREATE INDEX order_items_seller_idx ON olist.order_items(seller_id);
CREATE INDEX order_reviews_order_idx ON olist.order_reviews(order_id);

COMMENT ON SCHEMA olist IS
    'Relational import of the Olist Brazilian E-Commerce Public Dataset from Kaggle.';
COMMENT ON TABLE olist.orders IS
    'Public Olist order lifecycle data; original source file olist_orders_dataset.csv.';
COMMENT ON TABLE olist.order_items IS
    'Public Olist order line data with price, freight, seller, and product identifiers.';
COMMENT ON TABLE olist.order_payments IS
    'Public Olist order payment methods, installments, and payment values.';
COMMENT ON TABLE olist.order_reviews IS
    'Public Olist review scores and optional review text.';

CREATE ROLE datapilot_ro LOGIN PASSWORD 'local-read-only';
GRANT CONNECT ON DATABASE analytics TO datapilot_ro;
GRANT USAGE ON SCHEMA olist TO datapilot_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA olist TO datapilot_ro;
ALTER DEFAULT PRIVILEGES FOR ROLE analytics_owner IN SCHEMA olist
    GRANT SELECT ON TABLES TO datapilot_ro;
ALTER ROLE datapilot_ro SET default_transaction_read_only = on;
ALTER ROLE datapilot_ro SET statement_timeout = '15s';
ALTER ROLE datapilot_ro SET search_path = olist, public;

