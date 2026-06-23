#!/usr/bin/env python3
"""废弃 queue.json 测试 — 启动恢复只读 SQLite."""
import asyncio, sys, json; from pathlib import Path; sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
async def test():
    print(f"\n{'='*60}\n  废弃 queue.json 测试\n{'='*60}\n")
    import ui.views.download_view as dv
    orig = dv.QUEUE_FILE
    import tempfile; tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
    dv.QUEUE_FILE = Path(tmp.name)
    # Write queue.json that would have been loaded by old code
    with open(dv.QUEUE_FILE, "w") as f:
        json.dump({"88880":{"status":"已完成","tracks":{}},
                   "88881":{"status":"下载中","tracks":{}}}, f)
    # load_queue should skip terminal, load non-terminal as paused
    class FA: start_call=0; start_download=lambda s,rj:setattr(s,'start_call',s.start_call+1)
    v=dv.DownloadView.__new__(dv.DownloadView);v.app_controller=FA()
    v.active_downloads={};v.queue_list=type('o',(),{'controls':[],'update':lambda:None})()
    def mock_build(rj):
        v.active_downloads[rj]={"status":v.active_downloads.get(rj,{}).get("status",""),"tracks":{}}
    v.build_queue_item=mock_build;v.save_queue=lambda:None
    v.load_queue()
    assert "RJ88880" not in v.active_downloads,"已完成应被跳过"
    assert "RJ88881" in v.active_downloads,"下载中应被加载(作为paused)"
    assert v.app_controller.start_call==0,"不应调用 start_download"
    print(f"  ✓ queue.json terminal 被跳过, active 仅恢复 UI")
    dv.QUEUE_FILE=orig; import os; os.unlink(tmp.name)
    print(f"\n{'='*60}\n  ✓ 通过\n{'='*60}\n");return 0
if __name__=="__main__":sys.exit(asyncio.run(test()))
