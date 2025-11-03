# main.py
from fastapi import FastAPI, HTTPException, Query
from typing import Optional
from datetime import datetime, timedelta, date
import boto3, os, io
import pandas as pd
import pyarrow.parquet as pq

app = FastAPI(title="OHLCV S3 Price API (simple)")

# default bucket and region
S3_BUCKET = os.environ.get("S3_BUCKET", "ohlcv-pipeline")
S3_REGION = os.environ.get("AWS_REGION", "ap-south-1")

def get_session(access_key: Optional[str], secret_key: Optional[str], region: str = S3_REGION):
    if access_key and secret_key:
        return boto3.Session(aws_access_key_id=access_key, aws_secret_access_key=secret_key, region_name=region)
    return boto3.Session(region_name=region)

def read_parquet_bytes(b: bytes):
    buf = io.BytesIO(b)
    table = pq.read_table(buf)
    return table.to_pandas()

def normalize_symbol_for_bucket(sym: str, exchange: str = "NSE"):
    s = sym.strip().upper()
    if s.startswith(f"{exchange}_"):
        return s
    if not s.endswith("-EQ"):
        s = s + "-EQ"
    return f"{exchange}_{s}"

@app.get("/price/get/{params}")
def get_price(params: str,
              aws_access_key: Optional[str] = Query(None),
              aws_secret_key: Optional[str] = Query(None),
              exchange: str = Query("NSE"),
              max_files: int = Query(50)):
    """
    params: symbol,timeframe,range  e.g. CIPLA,15m,1d or NIFTY,5m,2y
    range: e.g. 1d, 7d, 3m, 1y
    """
    parts = [p.strip() for p in params.split(",")]
    if len(parts) != 3:
        raise HTTPException(status_code=400, detail="Use symbol,timeframe,range (e.g. CIPLA,15m,1d)")
    sym, timeframe, rng = parts
    symbol_partition = normalize_symbol_for_bucket(sym, exchange=exchange)

    # parse range -> start datetime
    now = datetime.utcnow()
    unit = rng[-1].lower()
    try:
        val = int(rng[:-1])
    except Exception:
        raise HTTPException(status_code=400, detail="Range malformed, use e.g. 1d,7d,3m,1y")
    if unit == "d":
        start = now - timedelta(days=val)
    elif unit == "m":
        start = now - timedelta(days=30 * val)
    elif unit == "y":
        start = now - timedelta(days=365 * val)
    else:
        raise HTTPException(status_code=400, detail="Unknown range unit; use d/m/y")

    sess = get_session(aws_access_key or os.environ.get("AWS_ACCESS_KEY_ID"),
                       aws_secret_key or os.environ.get("AWS_SECRET_ACCESS_KEY"),
                       S3_REGION)
    s3 = sess.client("s3")

    # iterate days in range and try to list parquet files under partitioned path
    rows = []
    files_read = 0
    date_iter = (start.date() + timedelta(days=i) for i in range((now.date() - start.date()).days + 1))
    prefixes_to_try_template = [
        # normal unencoded key style
        "processed/timeframe={timeframe}/exchange={exchange}/symbol={symbol}/year={Y}/month={m:02d}/day={d:02d}/",
        # encoded-style (if your pipeline URL encoded keys)
        "processed/timeframe%3D{timeframe}/exchange%3D{exchange}/symbol%3D{symbol}/year%3D{Y}/month%3D{m:02d}/day%3D{d:02d}/",
    ]

    for d in date_iter:
        for pfx_t in prefixes_to_try_template:
            prefix = pfx_t.format(timeframe=timeframe, exchange=exchange, symbol=symbol_partition, Y=d.year, m=d.month, d=d.day)
            paginator = s3.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=prefix):
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    if not key.lower().endswith(".parquet"):
                        continue
                    if files_read >= max_files:
                        break
                    resp = s3.get_object(Bucket=S3_BUCKET, Key=key)
                    b = resp["Body"].read()
                    try:
                        df = read_parquet_bytes(b)
                        rows.append(df)
                        files_read += 1
                    except Exception as e:
                        # skip bad files
                        print("skip", key, e)
                if files_read >= max_files:
                    break
            if files_read >= max_files:
                break
        if files_read >= max_files:
            break

    if not rows:
        raise HTTPException(status_code=404, detail="No parquet files found for query.")

    big = pd.concat(rows, ignore_index=True, sort=False)
    # try to coerce a timestamp column and filter
    for cand in ["timestamp", "ts", "time", "datetime", "date"]:
        if cand in big.columns:
            big[cand] = pd.to_datetime(big[cand], errors="coerce", utc=True)
            big = big[(big[cand] >= pd.to_datetime(start)) & (big[cand] <= pd.to_datetime(now))]
            break

    # return records (careful: might be big)
    return {"symbol": sym, "symbol_partition": symbol_partition, "timeframe": timeframe, "range": rng,
            "rows_returned": len(big), "data": big.to_dict(orient="records")}

@app.get("/price/get_by_key")
def get_by_key(key: str = Query(..., description="Full S3 key under bucket, e.g. processed/timeframe=15m/.../part-00021-....parquet"),
               aws_access_key: Optional[str] = Query(None),
               aws_secret_key: Optional[str] = Query(None)):
    sess = get_session(aws_access_key or os.environ.get("AWS_ACCESS_KEY_ID"),
                       aws_secret_key or os.environ.get("AWS_SECRET_ACCESS_KEY"),
                       S3_REGION)
    s3 = sess.client("s3")
    try:
        resp = s3.get_object(Bucket=S3_BUCKET, Key=key)
    except s3.exceptions.NoSuchKey:
        raise HTTPException(status_code=404, detail="Key not found in bucket.")
    b = resp["Body"].read()
    df = read_parquet_bytes(b)
    # If there is a timestamp column, convert to iso strings
    for cand in ["timestamp", "ts", "time", "datetime", "date"]:
        if cand in df.columns:
            df[cand] = pd.to_datetime(df[cand], errors="coerce", utc=True).dt.tz_convert(None)
            break
    return {"key": key, "rows": len(df), "data": df.to_dict(orient="records")}
