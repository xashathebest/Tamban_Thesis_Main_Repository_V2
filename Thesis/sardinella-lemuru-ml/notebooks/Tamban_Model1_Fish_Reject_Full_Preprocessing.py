# ================================================================
# TAMBAN MODEL 1 — COMPLETE COCO -> YOLO DATA PREPARATION
# For: Fish Defect Detection.v4i.coco (fish + reject = Fish 0)
# Run in ONE Colab cell AFTER original ZIP extraction / Drive mount.
# Requires EXTRACT, WORK, OUT from notebook setup. Does NOT rely on
# old COCO_FILES, records, split assignments or category mapping.
# ================================================================
import json, math, hashlib, random, re, shutil
from pathlib import Path
from collections import defaultdict, Counter
import cv2
import numpy as np
import pandas as pd
import yaml
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

# Set False to KEEP genuinely overlapping fish (recommended for robustness).
# True excludes only images listed in your PREVIOUSLY REVIEWED overlap CSV.
EXCLUDE_REVIEWED_OVERLAP_IMAGES = True
NEAR_DUP_HAMMING = 4
GROUP_CAPTURE_BURSTS = True
BURST_SECONDS = 15
VAL_FRACTION = 0.15
TEST_FRACTION = 0.15
SEED = 42
IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}

for var in ('EXTRACT', 'WORK', 'OUT'):
    if var not in globals():
        raise RuntimeError(f'Missing {var}. Run ZIP extraction/setup first.')
EXTRACT, WORK, OUT = map(lambda p: Path(p).resolve(), (EXTRACT, WORK, OUT))
if not EXTRACT.is_dir():
    raise FileNotFoundError(f'Original extracted COCO folder missing: {EXTRACT}')
if OUT == EXTRACT or EXTRACT in OUT.parents:
    raise RuntimeError('OUT must not be inside the original COCO extraction folder.')
AUDIT, FIGS = OUT/'audit', OUT/'figures'
AUDIT.mkdir(parents=True, exist_ok=True)
FIGS.mkdir(parents=True, exist_ok=True)

# 1) Load ORIGINAL JSON files from disk, never reuse previously filtered COCO_FILES.
COCO_FILES = []
for p in sorted(EXTRACT.rglob('*.json')):
    if p.stat().st_size > 250*1024*1024: continue
    try:
        j = json.loads(p.read_text(encoding='utf-8-sig'))
    except (ValueError, UnicodeError):
        continue
    if isinstance(j, dict) and all(k in j for k in ('images','annotations','categories')):
        COCO_FILES.append((p,j))
if not COCO_FILES:
    raise RuntimeError('No original COCO JSON files found under EXTRACT.')
original_n = sum(len(c['images']) for _,c in COCO_FILES)
print('Original COCO files:', [(str(p.relative_to(EXTRACT)),len(c['images'])) for p,c in COCO_FILES])
print('Original image entries:', original_n)

# 2) Preload reviewed overlap report (DO NOT mark every natural overlap as an error).
def norm_split(v):
    v = str(v).strip().lower()
    return {'valid':'val','validation':'val','training':'train','testing':'test'}.get(v,v)
def source_split(p):
    for part in p.relative_to(EXTRACT).parts:
        s = norm_split(part)
        if s in ('train','val','test'): return s
    return 'unspecified'

overlap_path = AUDIT/'potential_duplicate_fish_boxes.csv'
flagged_images = set()
if EXCLUDE_REVIEWED_OVERLAP_IMAGES:
    if not overlap_path.exists():
        raise FileNotFoundError(
            f'Reviewed overlap CSV not found: {overlap_path}. '
            'Restore the file or set EXCLUDE_REVIEWED_OVERLAP_IMAGES=False.'
        )
    flagged_df = pd.read_csv(overlap_path)
    if not {'split','image'}.issubset(flagged_df.columns):
        raise RuntimeError('Overlap CSV must contain split and image columns.')
    flagged_images = {(norm_split(x),Path(str(y)).name)
                      for x,y in zip(flagged_df['split'],flagged_df['image'])}
    print('Reviewed overlapping-image keys to exclude:',len(flagged_images))

# 3) Build name index for safe image resolution.
all_paths = [p for p in EXTRACT.rglob('*')
             if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
by_basename = defaultdict(list)
for p in all_paths: by_basename[p.name].append(p)
def find_image(jpath, filename):
    filename = str(filename).replace('\\','/').lstrip('/')
    name = Path(filename).name
    candidates = [jpath.parent/filename, EXTRACT/filename,
                  jpath.parent/name, jpath.parent/'images'/name]
    for p in candidates:
        if p.is_file(): return p.resolve()
    local = [p for p in by_basename[name] if p.parent == jpath.parent]
    if len(local)==1: return local[0].resolve()
    if len(by_basename[name])==1: return by_basename[name][0].resolve()
    return None

def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()

def phash(image):
    small = cv2.resize(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY),
                       (32,32), interpolation=cv2.INTER_AREA).astype(np.float32)
    low = cv2.dct(small)[:8,:8]
    med = np.median(low.ravel()[1:])
    ans=0
    for flag in (low > med).ravel(): ans=(ans<<1)|int(flag)
    return ans

records, issues, fixes, exclusions = [], [], [], []
category_counts, category_map = [], {}
for jpath,coco in COCO_FILES:
    split = source_split(jpath)
    ids = {int(c['id']):str(c['name']).strip().lower() for c in coco['categories']}
    keep_ids = {i for i,name in ids.items() if name in ('fish','reject')}
    reject_ids = {i for i,name in ids.items() if name=='reject'}
    category_map[str(jpath.relative_to(EXTRACT))] = {str(i):name for i,name in ids.items()}
    if not keep_ids:
        raise RuntimeError(f'No fish/reject classes in {jpath}')
    ann_by_image = defaultdict(list)
    for a in coco['annotations']: ann_by_image[a['image_id']].append(a)
    kept=0; fish_boxes=0; reject_used=0
    for obj in coco['images']:
        key=(split,Path(str(obj.get('file_name',''))).name)
        ref=f"{jpath.relative_to(EXTRACT)}::{obj['id']}::{obj.get('file_name','')}"
        anns=ann_by_image.get(obj['id'],[])
        chosen=[a for a in anns if int(a.get('category_id',-1)) in keep_ids]
        has_reject=any(int(a.get('category_id',-1)) in reject_ids for a in chosen)
        if not chosen:
            issues.append({'record':ref,'reason':'no_whole_fish_boxes','detail':''}); continue
        if key in flagged_images:
            exclusions.append({'record':ref,'reason':'reviewed_true_overlap','fish_boxes':len(chosen)})
            continue
        img_path = find_image(jpath,obj.get('file_name',''))
        if img_path is None:
            issues.append({'record':ref,'reason':'image_missing_or_ambiguous','detail':''});continue
        image=cv2.imread(str(img_path))
        if image is None:
            issues.append({'record':ref,'reason':'corrupt_image','detail':str(img_path)});continue
        H,W=image.shape[:2]
        if min(H,W)<32:
            issues.append({'record':ref,'reason':'too_small','detail':f'{W}x{H}'});continue
        try: dim_ok=abs(W-int(obj.get('width',W)))<=2 and abs(H-int(obj.get('height',H)))<=2
        except (ValueError,TypeError): dim_ok=False
        if not dim_ok:
            issues.append({'record':ref,'reason':'dimension_mismatch','detail':f'actual {W}x{H}'});continue
        boxes=[]; bad=None; dup=0
        for a in chosen:
            if a.get('iscrowd',0): bad='iscrowd';break
            try: x,y,bw,bh=map(float,a['bbox'])
            except (KeyError,TypeError,ValueError): bad='bad_bbox_format';break
            if not all(math.isfinite(v) for v in (x,y,bw,bh)) or bw<=0 or bh<=0:
                bad='invalid_bbox';break
            exceed=max(0.,-x,-y,x+bw-W,y+bh-H)
            if exceed>2: bad='out_of_bounds_gt_2px';break
            x1,y1,x2,y2=max(0.,x),max(0.,y),min(float(W),x+bw),min(float(H),y+bh)
            if x2-x1<2 or y2-y1<2: bad='bbox_under_2px';break
            box=[(x1+x2)/(2*W),(y1+y2)/(2*H),(x2-x1)/W,(y2-y1)/H]
            if any(all(abs(v-u)<1e-5 for v,u in zip(box,old)) for old in boxes):
                dup+=1;continue
            boxes.append(box)
            if exceed>0: fixes.append({'record':ref,'action':'clip_bbox_le_2px','annotation':a.get('id')})
        if bad or not boxes:
            issues.append({'record':ref,'reason':bad or 'no_boxes_after_checks','detail':''});continue
        if dup: fixes.append({'record':ref,'action':'remove_identical_boxes','count':dup})
        boxes.sort()
        small=cv2.resize(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY),(128,128),interpolation=cv2.INTER_AREA)
        records.append({'reference':ref,'source_path':img_path,'source_split':split,
                        'width':W,'height':H,'boxes':boxes,'fish_count':len(boxes),
                        'contains_reject':has_reject,'brightness':float(small.mean()),
                        'blur_metric':float(cv2.Laplacian(small,cv2.CV_64F).var()),
                        'sha':sha(img_path),'phash':phash(image),'duplicate_annotations_removed':dup})
        kept+=1;fish_boxes+=len(boxes);reject_used+=int(has_reject)
    category_counts.append({'split':split,'original_images':len(coco['images']),
                            'usable_before_exact_dedup':kept,'whole_fish_boxes':fish_boxes,
                            'images_with_reject_retained':reject_used})

pd.DataFrame(category_counts).to_csv(AUDIT/'category_counts.csv',index=False)
pd.DataFrame(issues,columns=['record','reason','detail']).to_csv(AUDIT/'quarantined_records.csv',index=False)
pd.DataFrame(fixes).to_csv(AUDIT/'automatic_label_fixes.csv',index=False)
pd.DataFrame(exclusions).to_csv(AUDIT/'excluded_reviewed_overlap_images.csv',index=False)
print('\nAfter label checks:',len(records),'images;',sum(r['fish_count'] for r in records),'whole-fish boxes')
print('Images containing rejected fish BEFORE exact dedup:',sum(r['contains_reject'] for r in records))
print('Excluded reviewed overlap images:',len(exclusions),' other issues:',len(issues))
if len(records)<100: raise RuntimeError('Too few usable images; inspect audit reports.')
if sum(r['contains_reject'] for r in records)==0:
    raise RuntimeError('Zero recovered Reject images. Verify original COCO files/categories.')

# 4) Remove byte-identical images ONLY when all labels agree.
sha_groups=defaultdict(list)
for r in records: sha_groups[r['sha']].append(r)
unique,dropped,conflicts=[],[],[]
for hashval,grp in sha_groups.items():
    sig={tuple(tuple(round(v,5) for v in box) for box in r['boxes']) for r in grp}
    if len(sig)>1:
        conflicts.append({'sha':hashval,'records':[r['reference'] for r in grp]});continue
    grp.sort(key=lambda r:({'test':0,'val':1,'train':2}.get(r['source_split'],3),r['reference']))
    unique.append(grp[0]);dropped+=grp[1:]
(AUDIT/'exact_label_conflicts.json').write_text(json.dumps(conflicts,indent=2))
if conflicts:
    raise RuntimeError(f'{len(conflicts)} exact-image label conflicts. See exact_label_conflicts.json')
records=unique
pd.DataFrame([{'record':r['reference'],'sha':r['sha']} for r in dropped]).to_csv(
    AUDIT/'removed_exact_duplicates.csv',index=False)

# 5) Group Roboflow derivatives, near duplicates, optional capture bursts.
class DSU:
    def __init__(self,n): self.p=list(range(n))
    def root(self,i):
        while self.p[i]!=i:
            self.p[i]=self.p[self.p[i]];i=self.p[i]
        return i
    def union(self,i,j):
        a,b=self.root(i),self.root(j)
        if a!=b:self.p[b]=a

def origin(stem):
    stem=re.sub(r'(?i)_(jpg|jpeg|png|bmp|webp)\.rf\.[a-z0-9]+$','',stem)
    return re.sub(r'(?i)\.rf\.[a-z0-9]+$','',stem).lower()

def burst(stem):
    match=re.search(r'WIN_(\d{8})_(\d\d)_(\d\d)_(\d\d)',stem,re.I)
    if not match:return None
    day,h,m,s=match.groups()
    return (day,(int(h)*3600+int(m)*60+int(s))//BURST_SECONDS)

N=len(records);uf=DSU(N)
origins=defaultdict(list)
for i,r in enumerate(records):origins[origin(r['source_path'].stem)].append(i)
for indexes in origins.values():
    for i in indexes[1:]:uf.union(indexes[0],i)
near_pairs=[]
for i in range(N):
    a=records[i]
    for j in range(i+1,N):
        b=records[j]
        if a['fish_count']!=b['fish_count']:continue
        aspect_a=a['width']/a['height'];aspect_b=b['width']/b['height']
        if abs(aspect_a-aspect_b)/max(aspect_a,aspect_b)>0.035:continue
        if abs(a['brightness']-b['brightness'])>20:continue
        dist=(a['phash']^b['phash']).bit_count()
        if dist<=NEAR_DUP_HAMMING:
            uf.union(i,j)
            if len(near_pairs)<20000:
                near_pairs.append({'a':a['reference'],'b':b['reference'],'phash_distance':dist})
if GROUP_CAPTURE_BURSTS:
    bursts=defaultdict(list)
    for i,r in enumerate(records):
        b=burst(r['source_path'].stem)
        if b is not None:bursts[b].append(i)
    if max((len(v) for v in bursts.values()),default=0)>0.35*N:
        print('WARNING: skipped burst grouping; oversized capture burst')
    else:
        for indexes in bursts.values():
            for i in indexes[1:]:uf.union(indexes[0],i)
group_members=defaultdict(list)
for i,r in enumerate(records):
    r['group']=uf.root(i);group_members[r['group']].append(i)
pd.DataFrame(near_pairs,columns=['a','b','phash_distance']).to_csv(AUDIT/'near_duplicate_pairs.csv',index=False)
print('Unique images:',N,'duplicate groups:',len(group_members),'exact copies removed:',len(dropped))
if len(group_members)<12:
    raise RuntimeError('Too few independent groups; inspect capture-session grouping.')

# 6) Group-exclusive balanced INTERNAL split.
items=list(group_members.items())
rng=random.Random(SEED);rng.shuffle(items);items.sort(key=lambda x:len(x[1]),reverse=True)
target={'train':N*(1-VAL_FRACTION-TEST_FRACTION),'val':N*VAL_FRACTION,'test':N*TEST_FRACTION}
counts={'train':0,'val':0,'test':0};assignments={}
for gid,members in items:
    size=len(members)
    allowed=[s for s in ('train','val','test') if s=='train' or counts[s]+size<=target[s]*1.10]
    if not allowed:allowed=['train']
    def score(s):
        proposed=dict(counts);proposed[s]+=size
        return sum((proposed[k]-target[k])**2/max(target[k],1) for k in counts)
    split=min(allowed,key=score)
    assignments[gid]=split;counts[split]+=size
for r in records:r['split']=assignments[r['group']]
if min(counts.values())<min(30,max(1,int(N*.05))):
    raise RuntimeError(f'Holdout split too small: {counts}; review grouping')
assert all(len({records[i]['split'] for i in inds})==1 for inds in group_members.values())
print('Group-exclusive split:',counts)

# 7) Write clean YOLO dataset, leaving original extracted dataset untouched.
YOLO_DATA=WORK/'yolo_cleaned'
if EXTRACT==YOLO_DATA or EXTRACT in YOLO_DATA.parents:
    raise RuntimeError('YOLO_DATA must not contain original EXTRACT folder')
if any(YOLO_DATA in r['source_path'].parents for r in records):
    raise RuntimeError('Refusing to delete output containing source images.')
if YOLO_DATA.exists():shutil.rmtree(YOLO_DATA)
for split in ('train','val','test'):
    (YOLO_DATA/'images'/split).mkdir(parents=True,exist_ok=True)
    (YOLO_DATA/'labels'/split).mkdir(parents=True,exist_ok=True)
manifest=[]
for i,r in enumerate(records):
    ext=r['source_path'].suffix.lower();base=f'fish_{i:06d}{ext}'
    dst=YOLO_DATA/'images'/r['split']/base
    shutil.copy2(r['source_path'],dst)
    label=YOLO_DATA/'labels'/r['split']/(Path(base).stem+'.txt')
    label.write_text('\n'.join('0 '+' '.join(f'{v:.8f}' for v in b) for b in r['boxes'])+'\n',encoding='utf-8')
    r['dest_path']=dst
    manifest.append({'record':r['reference'],'source':str(r['source_path']),
        'clean_image':str(dst),'original_split':r['source_split'],'split':r['split'],
        'group':r['group'],'fish_boxes':len(r['boxes']),
        'contains_reject':r['contains_reject'],'brightness':r['brightness'],
        'blur_metric':r['blur_metric'],'sha256':r['sha']})
DATA_YAML=YOLO_DATA/'data.yaml'
DATA_YAML.write_text(yaml.safe_dump({'path':str(YOLO_DATA),'train':'images/train',
    'val':'images/val','test':'images/test','nc':1,'names':{0:'Fish'}},sort_keys=False))
pd.DataFrame(manifest).to_csv(AUDIT/'image_manifest.csv',index=False)

# 8) Persist audit and plots.
recovered=sum(r['contains_reject'] for r in records)
summary={'original_image_entries':original_n,'cleaned_images':N,
    'whole_fish_boxes':sum(len(r['boxes']) for r in records),
    'recovered_images_containing_reject':recovered,
    'exact_duplicates_removed':len(dropped),
    'reviewed_overlap_images_excluded':len(exclusions),
    'quarantined':len(issues),'near_duplicate_pairs':len(near_pairs),
    'distinct_groups':len(group_members),'split_counts':counts,
    'source_categories':category_map,'target_class':'Fish',
    'note':'Grouped internal holdout. NOT an independent capture-session test.'}
(AUDIT/'audit_summary.json').write_text(json.dumps(summary,indent=2))
fig,axs=plt.subplots(1,2,figsize=(11,4))
axs[0].bar(list(counts),list(counts.values()));axs[0].set_title('Grouped image split')
axs[1].hist([len(r['boxes']) for r in records],bins=30)
axs[1].set_title('Fish annotations per image');axs[1].set_xlabel('Fish count')
plt.tight_layout();plt.savefig(FIGS/'dataset_summary.png',dpi=170);plt.show();plt.close()
plt.figure(figsize=(8,4))
for s in ('train','val','test'):
    vals=[r['brightness'] for r in records if r['split']==s]
    plt.hist(vals,bins=20,alpha=.45,label=f'{s} ({len(vals)})')
plt.title('Image brightness by split');plt.xlabel('Brightness (0-255)');plt.legend()
plt.tight_layout();plt.savefig(FIGS/'lighting_distribution.png',dpi=170);plt.show();plt.close()
fig,axs=plt.subplots(3,3,figsize=(12,12))
for row,s in enumerate(('train','val','test')):
    pool=[r for r in records if r['split']==s]
    for col,r in enumerate(random.Random(SEED+row).sample(pool,min(3,len(pool)))):
        im=cv2.imread(str(r['source_path']));im=cv2.cvtColor(im,cv2.COLOR_BGR2RGB)
        h,w=im.shape[:2];ax=axs[row,col];ax.imshow(im)
        for x,y,bw,bh in r['boxes']:
            ax.add_patch(Rectangle(((x-bw/2)*w,(y-bh/2)*h),bw*w,bh*h,
                                   fill=False,edgecolor='lime',linewidth=1.2))
        ax.set_title(f'{s}: {len(r["boxes"])} fish; Reject={r["contains_reject"]}');ax.axis('off')
for ax in axs.flat:
    if not ax.has_data():ax.axis('off')
plt.tight_layout();plt.savefig(FIGS/'annotation_samples.png',dpi=140);plt.show();plt.close()
for s in ('train','val','test'):
    n_img=len(list((YOLO_DATA/'images'/s).iterdir()))
    n_lab=len(list((YOLO_DATA/'labels'/s).glob('*.txt')))
    assert n_img==n_lab==counts[s],f'{s} output count mismatch'
print('\n'+'='*64)
print('CLEAN MODEL 1 DATASET READY')
print('Original COCO images:',original_n)
print('Clean images:',N,' | Whole fish boxes:',summary['whole_fish_boxes'])
print('Recovered Reject-containing images:',recovered)
print('Reviewed overlapping images excluded:',len(exclusions))
print('Train/Val/Test:',counts)
print('YOLO data.yaml:',DATA_YAML)
print('Audit & graphs:',AUDIT,FIGS)
print('IMPORTANT: GPU must be enabled before YOLO training.')
print('='*64)
