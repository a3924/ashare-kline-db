# -*- coding: utf-8 -*-
"""bake_kline_db.py v2 — 全市场A股/ETF 5年前复权日K 分片。
策略：低并发温和节流防封；东财(push2his/push2delay)优先，空则腾讯gtimg(3窗)兜底；
每只两种源都拿不到才跳过。已存在的分片自动跳过（可断点续跑）。
产出 db/{VER}/{sh|sz}{code}.json + manifest.json
"""
import json, os, sys, time, random, threading, ssl, urllib.request, re

HERE = os.path.dirname(os.path.abspath(__file__))
UNI_JS = r"E:\AI\我的模拟人生A股版-在线版\data_universe.js"
VER = "20260901"
BEG = "20210901"
END = VER
OUT = os.path.join(HERE, "db", VER)
MAX = 2000
F2 = "fields2=f51,f52,f53,f54,f55,f56"
lock = threading.Lock()
stats = {"em": 0, "tx": 0, "empty": 0, "err": 0}
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
      "Referer": "https://quote.eastmoney.com/"}
HOSTS = ["push2his.eastmoney.com", "push2delay.eastmoney.com"]
ctx = ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=ctx))


def load_uni():
    txt = open(UNI_JS, encoding="utf-8").read()
    obj = json.loads(txt[txt.find("{"):txt.rfind("}") + 1])
    out = [s["c"] for s in obj.get("stocks", [])] + [e["c"] for e in obj.get("etfs", [])]
    return out


def get_json(url, timeout=15):
    req = urllib.request.Request(url, headers=UA)
    with DIRECT.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def em_rows(code):
    secid = ("1." if code[0] in "56" else "0.") + code
    for host in HOSTS:
        for t in range(2):
            try:
                url = ("https://%s/api/qt/stock/kline/get?secid=%s&klt=101&fqt=1&beg=%s&end=%s&lmt=%d&fields1=f1,f2,f3&%s"
                       % (host, secid, BEG, END, MAX, F2))
                d = get_json(url)
                kl = (d.get("data") or {}).get("klines") or []
                if kl:
                    return _pack(kl)
                time.sleep(1.5 * (t + 1))   # 疑似节流 -> 短等重试
            except Exception:
                time.sleep(1.2 + random.random())
    return None


def tx_rows(code):
    """腾讯 gtimg：3 窗拼 5 年（每天窗≤640根）"""
    full = ("sh" if code[0] in "56" else "sz") + code
    end = "%s-%s-%s" % (END[:4], END[4:6], END[6:8])
    seg = [["2021-09-01", "2023-08-31"], ["2023-09-01", "2025-08-29"], ["2025-09-01", end]]
    merged = {}
    for s0, s1 in seg:
        got = False
        for t in range(3):
            try:
                url = ("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=%s,day,%s,%s,640,qfq" % (full, s0, s1))
                d = get_json(url)
                node = ((d or {}).get("data") or {}).get(full) or {}
                arr = node.get("qfqday") or node.get("day") or []
                if arr:
                    for b in arr:
                        dt = int(b[0].replace("-", ""))
                        if dt > int(END):
                            continue
                        if dt not in merged:
                            merged[dt] = (dt, float(b[1]), float(b[2]), float(b[3]), float(b[4]), float(b[5]))
                    got = True
                else:
                    time.sleep(1.0)
            except Exception:
                time.sleep(1.0 * (t + 1))
        if not got:
            return None
    if not merged:
        return None
    return "|".join("%d,%.2f,%.2f,%.2f,%.2f,%d" % row for row in (merged[k] for k in sorted(merged)))


def _pack(kl):
    parts = []
    for line in kl:
        f = line.split(",")
        if len(f) < 6:
            continue
        dt = f[0].replace("-", "")
        parts.append("%s,%.2f,%.2f,%.2f,%.2f,%d" % (dt, float(f[1]), float(f[2]), float(f[3]), float(f[4]), int(float(f[5]))))
    return "|".join(parts) if parts else None


def work(codes, start, step):
    for idx in range(start, len(codes), step):
        code = codes[idx]
        shard = os.path.join(OUT, ("sh" if code[0] in "56" else "sz") + code + ".json")
        if os.path.exists(shard):
            with lock:
                stats["ok"] += 1
            continue
        k = em_rows(code)
        src = "em"
        if not k:
            k = tx_rows(code)
            src = "tx"
        if not k:
            with lock:
                stats["empty"] += 1
            continue
        tmp = shard + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"end": int(END), "k": k}, fh, ensure_ascii=False)
        os.replace(tmp, shard)
        with lock:
            stats[src] += 1
            stats["ok"] = stats["em"] + stats["tx"]
            if stats["ok"] % 200 == 0:
                print("progress ok=%d em=%d tx=%d empty=%d err=%d"
                      % (stats["ok"], stats["em"], stats["tx"], stats["empty"], stats.get("err", 0)), flush=True)
        time.sleep(random.uniform(0.35, 0.9))   # 温和节流，降低整IP被封概率


def main():
    codes = load_uni()
    os.makedirs(OUT, exist_ok=True)
    print("universe total=%d out=%s" % (len(codes), OUT), flush=True)
    t0 = time.time()
    nw = 5
    ths = []
    for w in range(nw):
        th = threading.Thread(target=work, args=(codes, w, nw))
        th.start()
        ths.append(th)
    for th in ths:
        th.join()
    nfiles = sum(1 for fn in os.listdir(OUT) if fn.endswith(".json"))
    man = {"ver": VER, "end": int(END), "n": nfiles, "em": stats["em"], "tx": stats["tx"],
           "updated": time.strftime("%Y-%m-%d"), "bake_sec": round(time.time() - t0)}
    with open(os.path.join(HERE, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(man, fh, ensure_ascii=False, indent=1)
    print("DONE ok=%d em=%d tx=%d empty=%d files=%d secs=%.0f"
          % (stats["ok"], stats["em"], stats["tx"], stats["empty"], nfiles, time.time() - t0), flush=True)


if __name__ == "__main__":
    main()
