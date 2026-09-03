# -*- coding: utf-8 -*-
"""update_db.py — GitHub Actions 每日刷新全市场日K分片（新建 db/{today} 目录 + 更新 manifest）。
数据源：东财 push2his/push2delay -> 腾讯 gtimg 兜底。低并发温和节流。
分片格式与游戏端一致：{"end": yyyymmdd, "k": "dt,o,c,h,l,v|..."}
"""
import json, os, time, random, threading, urllib.request, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
END = datetime.date.today().strftime("%Y%m%d")       # 刷新到当日
BEG = "20210901"
OUT = os.path.join(HERE, "db", END)
MAX = 2000
F2 = "fields2=f51,f52,f53,f54,f55,f56"
HOSTS = ["push2his.eastmoney.com", "push2delay.eastmoney.com"]
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 Safari/537.36",
      "Referer": "https://quote.eastmoney.com/"}
lock = threading.Lock()
stats = {"ok": 0}


def codes():
    with open(os.path.join(HERE, "codes.txt"), encoding="utf-8") as fh:
        return [l.strip() for l in fh if l.strip()]


def get_json(url, timeout=18):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
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
                    return "|".join(
                        "%s,%.2f,%.2f,%.2f,%.2f,%d" % (
                            f[0].replace("-", ""), float(f[1]), float(f[2]), float(f[3]), float(f[4]), int(float(f[5])))
                        for f in (x.split(",") for x in kl) if len(f) >= 6)
                time.sleep(1.2)
            except Exception:
                time.sleep(1.0 + random.random())
    return None


def tx_rows(code):
    full = ("sh" if code[0] in "56" else "sz") + code
    e = "%s-%s-%s" % (END[:4], END[4:6], END[6:8])
    seg = [["2021-09-01", "2023-08-31"], ["2023-09-01", "2025-08-29"], ["2025-09-01", e]]
    merged = {}
    for s0, s1 in seg:
        got = False
        for t in range(3):
            try:
                d = get_json("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=%s,day,%s,%s,640,qfq" % (full, s0, s1))
                arr = (((d or {}).get("data") or {}).get(full) or {}).get("qfqday") or []
                if arr:
                    for b in arr:
                        dt = int(b[0].replace("-", ""))
                        if dt <= int(END) and dt not in merged:
                            merged[dt] = (dt, float(b[1]), float(b[2]), float(b[3]), float(b[4]), float(b[5]))
                    got = True
            except Exception:
                time.sleep(1.0 * (t + 1))
        if not got:
            return None
    if not merged:
        return None
    return "|".join("%d,%.2f,%.2f,%.2f,%.2f,%d" % row for row in (merged[k] for k in sorted(merged)))


def work(codes, start, step):
    for idx in range(start, len(codes), step):
        code = codes[idx]
        shard = os.path.join(OUT, ("sh" if code[0] in "56" else "sz") + code + ".json")
        if os.path.exists(shard):
            continue
        k = em_rows(code) or tx_rows(code)
        if not k:
            continue
        tmp = shard + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"end": int(END), "k": k}, fh, ensure_ascii=False)
        os.replace(tmp, shard)
        with lock:
            stats["ok"] += 1
            if stats["ok"] % 300 == 0:
                print("progress ok=%d" % stats["ok"], flush=True)
        time.sleep(random.uniform(0.2, 0.6))


def prune_old(keep=3):
    """db/ 下只保留最近 keep 个日期目录，防止仓库无限膨胀"""
    try:
        dirs = [d for d in os.listdir(os.path.join(HERE, "db")) if os.path.isdir(os.path.join(HERE, "db", d)) and len(d) == 8]
        dirs.sort(reverse=True)
        for d in dirs[keep:]:
            import shutil
            shutil.rmtree(os.path.join(HERE, "db", d))
            print("pruned old dir", d, flush=True)
    except Exception as e:
        print("prune warn", repr(e), flush=True)


def main():
    prune_old(3)
    cs = codes()
    os.makedirs(OUT, exist_ok=True)
    print("total", len(cs), "->", OUT, flush=True)
    ths = []
    for w in range(4):
        th = threading.Thread(target=work, args=(cs, w, 4))
        th.start()
        ths.append(th)
    for th in ths:
        th.join()
    n = sum(1 for fn in os.listdir(OUT) if fn.endswith(".json"))
    man = {"ver": END, "end": int(END), "n": n, "updated": END,
           "note": "auto by GitHub Actions"}
    with open(os.path.join(HERE, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(man, fh, ensure_ascii=False, indent=1)
    print("DONE files", n, flush=True)


if __name__ == "__main__":
    main()
