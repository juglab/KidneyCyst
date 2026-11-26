"""Browser walkthrough of the KidneyCyst app (start page -> run page -> review -> other-tab guard).

Usage: python ui_flow_test.py <work dir with data/Run3/Plate1 and data/Run3/Plate2 TIFFs, screenshots go here>
Needs a server on 127.0.0.1:8799 with KIDNEYCYST_TOKEN=shot and an empty KIDNEYCYST_HOME, and playwright + Chrome.
Prints PASS/FAIL lines; exit code 1 on any failure.
"""
import time, sys, json, urllib.request
from playwright.sync_api import sync_playwright
SC=sys.argv[1]; D1=SC+"/data/Run3/Plate1"; D2=SC+"/data/Run3/Plate2"; B="http://127.0.0.1:8799"
def wait_done(pg):
    for _ in range(240):
        time.sleep(1)
        if not pg.is_visible("#runBox") and pg.is_visible("#doneBox"): return True
    return False
with sync_playwright() as p:
    br=p.chromium.launch(executable_path="/usr/bin/google-chrome"); ctx=br.new_context(viewport={"width":1280,"height":900})
    errs=[]; ctx.on("weberror", lambda e: errs.append(str(e.error)))
    a=ctx.new_page(); a.goto(B+"/?t=shot"); time.sleep(1.5); a.screenshot(path=SC+"/ia1_start_empty.png",full_page=True)
    a.fill("#pathIn",D1); a.click("#usePath"); a.wait_for_url("**/run**"); time.sleep(1.5); a.screenshot(path=SC+"/ia2_run_new.png",full_page=True)
    a.click("#start"); time.sleep(4); a.screenshot(path=SC+"/ia3_run_running.png",full_page=True)
    print("run1 done:",wait_done(a)); time.sleep(1); a.screenshot(path=SC+"/ia4_run_detected.png",full_page=True); print("url:",a.url.split("?")[1][:20])
    id1=a.url.split("id=")[1].split("&")[0]
    a.click("#review"); a.wait_for_url("**/review**"); time.sleep(3); print("review header:",a.inner_text("#runName"))
    a.keyboard.press("a"); time.sleep(2); a.click("#home"); a.wait_for_url("**/run**"); time.sleep(1.5); a.screenshot(path=SC+"/ia5_run_inreview.png",full_page=True)
    a.click("#back"); a.wait_for_url(B+"/?**"); time.sleep(1.5)
    a.fill("#pathIn",D2); a.click("#usePath"); a.wait_for_url("**/run**"); time.sleep(1); a.click("#start"); print("run2 done:",wait_done(a))
    id2=a.url.split("id=")[1].split("&")[0]
    a.click("#back"); a.wait_for_url(B+"/?**"); time.sleep(1.5); a.screenshot(path=SC+"/ia6_start_two_runs.png",full_page=True)
    # tab conflict: tab A shows run1, tab C reviews run1, tab B opens run2
    a.goto(f"{B}/run?id={id1}&t=shot"); time.sleep(1.5)
    c=ctx.new_page(); c.goto(f"{B}/review?id={id1}&t=shot"); time.sleep(3)
    b=ctx.new_page(); b.goto(f"{B}/run?id={id2}&t=shot"); time.sleep(1.5); print("tab B shows:",b.inner_text("#rName"))
    a.bring_to_front(); a.click("#openFolder"); time.sleep(1.5); print("tab A banner visible:",a.is_visible("#otherRun"))
    a.screenshot(path=SC+"/ia7_other_run_banner.png",full_page=False)
    c.bring_to_front(); c.keyboard.press("n"); time.sleep(2); print("review modal:",c.inner_text("#mTitle") if c.is_visible("#mTitle") else None)
    c.screenshot(path=SC+"/ia8_review_other_run.png")
    st=json.load(urllib.request.urlopen(urllib.request.Request(B+"/api/library",headers={"X-Token":"shot"})))
    print("statuses:",[(r["name"],r["status"],r["reviewed"]) for r in st["runs"]])
    print("errors:",errs)
    br.close()
