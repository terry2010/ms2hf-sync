"""Read-only repo diff for the ms2hf-sync workflows.

Env inputs:
  COMPARE_SRC_REPO / COMPARE_DST_REPO   owner/name
  COMPARE_REPO_TYPE                     model | dataset (default: model)
  COMPARE_DIRECTION                     dispatch direction string, e.g.
                                        "ModelScope → HuggingFace" (default)
  COMPARE_NOTE                          extra line shown under the title
  HF_TOKEN / MS_TOKEN                   optional credentials
  GITHUB_STEP_SUMMARY                   optional path to write the report to

Lists file metadata on both platforms, classifies each source file as
identical / changed / missing / unverifiable, lists target-only files,
prints a 3-column (source | target | result) HTML table and appends it
to the step summary when available.
"""
import html
import os
import sys

from huggingface_hub import HfApi
from huggingface_hub.hf_api import RepoFile
from modelscope.hub.api import HubApi
from ms2hf import ModelScopeBackend, _hf_repo_type

src_repo = os.environ["COMPARE_SRC_REPO"]
dst_repo = os.environ["COMPARE_DST_REPO"]
repo_type = os.environ.get("COMPARE_REPO_TYPE", "model")
direction = os.environ.get("COMPARE_DIRECTION", "ModelScope → HuggingFace")
note = os.environ.get("COMPARE_NOTE", "")
ms_to_hf = direction.strip().startswith("ModelScope")
src_name, dst_name = ("ModelScope", "HuggingFace") if ms_to_hf else ("HuggingFace", "ModelScope")


def ms_meta(repo_id):
    api = HubApi()
    tok = os.environ.get("MS_TOKEN")
    if tok:
        api.login(tok)
    if repo_type == "model":
        out = {}
        for f in api.get_model_files(model_id=repo_id, recursive=True,
                                     use_cookies=bool(tok)):
            if f.get("Type") == "tree" or not f.get("Path"):
                continue
            out[f["Path"]] = {"sha": (f.get("Sha256") or "").lower() or None,
                              "size": f.get("Size")}
        return out
    b = ModelScopeBackend(token=tok)
    return {f.path: {"sha": None, "size": f.size}
            for f in b.list_files(repo_id, repo_type, None)}


def hf_meta(repo_id):
    api = HfApi(token=os.environ.get("HF_TOKEN"))
    out = {}
    for e in api.list_repo_tree(repo_id, repo_type=_hf_repo_type(repo_type),
                                recursive=True):
        if not isinstance(e, RepoFile):
            continue
        out[e.path] = {"sha": e.lfs.sha256.lower() if e.lfs else None,
                       "size": e.size}
    return out


def size_str(sz):
    if sz is None:
        return "?"
    n = int(sz)
    if n >= 1024**3:
        return f"{n/1024**3:.2f} GB"
    if n >= 1024**2:
        return f"{n/1024**2:.1f} MB"
    if n >= 1024:
        return f"{n/1024:.1f} KB"
    return f"{n} B"


src = (ms_meta if ms_to_hf else hf_meta)(src_repo)
if not src:
    sys.exit(f"source repo {src_repo} listed 0 files - aborting")

dst, dst_err = None, None
try:
    dst = (hf_meta if ms_to_hf else ms_meta)(dst_repo)
except Exception as e:  # noqa: BLE001 - report and continue with empty target
    dst_err = e
    dst = {}

identical, changed, src_only, unverifiable = [], [], [], []
for p, sm in sorted(src.items()):
    dm = dst.get(p)
    if dm is None:
        src_only.append(p)
        continue
    if sm["sha"] and dm["sha"]:
        if sm["sha"] == dm["sha"]:
            identical.append(p)
        else:
            changed.append((p, "sha256 不同"))
        continue
    if sm["size"] is not None and dm["size"] is not None \
            and int(sm["size"]) != int(dm["size"]):
        changed.append((p, f"大小不同 {size_str(sm['size'])} → {size_str(dm['size'])}"))
        continue
    sz = int(sm["size"] or dm["size"] or 0)
    if sz < 100 * 1024 * 1024:
        unverifiable.append((p, "无 hash 可比对（小文件）"))
    else:
        unverifiable.append((p, f"无 hash 可比对（{size_str(sz)}）"))

dst_only = sorted(set(dst) - set(src))


def cell(m, p):
    if not m:
        return ""
    return f"<code>{html.escape(p)}</code><br><sub>{size_str(m.get('size'))}</sub>"


CAP = 200


def sec(rows, title, items):
    rows.append(f'<tr><td colspan="3"><b>{title}（{len(items)} 个）</b></td></tr>')
    rows.extend(items[:CAP])
    if len(items) > CAP:
        rows.append(f'<tr><td colspan="3"><i>…另有 {len(items)-CAP} 个，见日志</i></td></tr>')


def tr(*cells_):
    return "<tr>" + "".join(f"<td>{x}</td>" for x in cells_) + "</tr>"


R = ["<h3>仓库差异对比</h3>"]
if note:
    R.append(f"<p><i>{html.escape(note)}</i></p>")
R.append(f"<p>源（{src_name}）<code>{src_repo}</code>：{len(src)} 个文件 ｜ "
         f"目标（{dst_name}）<code>{dst_repo}</code>："
         + (f"列取失败" if dst_err else f"{len(dst)} 个文件") + "</p>")
if dst_err:
    R.append(f"<p>⚠️ 目标仓列取失败（<code>{html.escape(str(dst_err))}</code>），以下把目标视为空</p>")
R.append("<table>")
R.append("<tr><th>源</th><th>目标</th><th>结果</th></tr>")

if src_only:
    sec(R, "🔴 只在源仓", [tr(cell(src[p], p), "", "待传输") for p in src_only])
if dst_only:
    sec(R, "🟣 只在目标仓", [tr("", cell(dst[p], p), "mirror 会删") for p in dst_only])
if changed:
    sec(R, "🔶 内容不同", [tr(cell(src[p], p), cell(dst[p], p), why) for p, why in changed])
if unverifiable:
    sec(R, "⚪ 无法比对", [tr(cell(src[p], p), cell(dst[p], p), why) for p, why in unverifiable])
if identical:
    sec(R, "✅ 一致", [tr(cell(src[p], p), cell(dst[p], p), "sha256 相同") for p in identical])
R.append("</table>")

report = "\n".join(R)
print(report)
summary = os.environ.get("GITHUB_STEP_SUMMARY")
if summary:
    with open(summary, "a") as f:
        f.write(report + "\n")
