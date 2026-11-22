"""일회성 독립 검수: 생산 코드/원본을 변경하지 않는다."""
import csv,hashlib,json,math,re,statistics
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from decimal import Decimal

ROOT=Path(__file__).resolve().parent.parent
OUT=ROOT/'outputs'
from political_analysis.pipeline import verify_dataset_certificate
quality=verify_dataset_certificate(ROOT/'data/processed/analysis_dataset.csv',OUT/'data_quality.json')
origin_manifest=json.loads((OUT/'exploration_manifest.json').read_text())
assert origin_manifest['dataset_sha256']==quality['dataset_sha256']
assert hashlib.sha256((OUT/'data_quality.json').read_bytes()).hexdigest()==origin_manifest['quality_sha256']
def read(path,encoding='utf-8'):
 with path.open(encoding=encoding,newline='') as handle:return list(csv.DictReader(handle))
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def quantile(values,p):
 values=sorted(values);at=(len(values)-1)*p;low=math.floor(at);high=math.ceil(at)
 return values[low]+(values[high]-values[low])*(at-low)
def equal(actual,expected):return math.isclose(float(actual),float(expected),rel_tol=1e-12,abs_tol=1e-10)
def write(path,rows):
 with path.open('w',encoding='utf-8',newline='') as handle:
  writer=csv.DictWriter(handle,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)

data=read(ROOT/'data/processed/analysis_dataset.csv','utf-8-sig')
stats=read(OUT/'tables/descriptive_statistics.csv')
pairs=read(OUT/'tables/correlation_pairs.csv')
matrix=read(OUT/'tables/correlations.csv')
checks=0
for row in stats:
 col=row[''];values=[float(r[col]) for r in data if r[col]!='']
 independent={'count':len(values),'mean':statistics.fmean(values),'std':statistics.stdev(values),
              'min':min(values),'25%':quantile(values,.25),'50%':quantile(values,.5),
              '75%':quantile(values,.75),'max':max(values),'missing':len(data)-len(values)}
 for name,value in independent.items():
  assert equal(row[name],value),(col,name,row[name],value);checks+=1
independent_pairs=[]
for x,y in combinations(['turnout','aging_rate','oldest_share'],2):
 complete=[(float(r[x]),float(r[y])) for r in data if r[x]!='' and r[y]!='']
 xs,ys=zip(*complete);xm,ym=statistics.fmean(xs),statistics.fmean(ys)
 coefficient=math.fsum((a-xm)*(b-ym) for a,b in complete)/math.sqrt(math.fsum((a-xm)**2 for a in xs)*math.fsum((b-ym)**2 for b in ys))
 published=next(r for r in pairs if r['x']==x and r['y']==y)
 assert int(published['n'])==len(complete) and published['status']=='ok'
 assert abs(float(published['pearson_r'])-coefficient)<1e-12
 for a,b in [(x,y),(y,x)]:
  assert abs(float(next(r for r in matrix if r['']==a)[b])-coefficient)<1e-12
 independent_pairs.append({'x':x,'y':y,'n':len(complete),'pearson_r':coefficient})

continuous=['turnout','aging_rate','oldest_share','fiscal_independence','net_migration_rate','log_population']
flags=[];thresholds={}
for col in continuous:
 values=[float(r[col]) for r in data];q1,q3=quantile(values,.25),quantile(values,.75)
 low,high=q1-1.5*(q3-q1),q3+1.5*(q3-q1)
 threshold={'q1':q1,'q3':q3,'low':low,'high':high,'candidate_count':0}
 for r in data:
  value=float(r[col])
  if value<low or value>high:
   flags.append({'region_code':r['region_code'],'province':r['province'],'region_name':r['region_name'],'variable':col,'value':value,'lower_fence':low,'upper_fence':high,'rule':'1.5_IQR','action':'retain_pending_influence_diagnostics'})
   threshold['candidate_count']+=1
 thresholds[col]=threshold
extremes=[]
for col in ['turnout','aging_rate','oldest_share']:
 low=min(float(r[col]) for r in data);high=max(float(r[col]) for r in data)
 for label,value in [('min',low),('max',high)]:
  for r in data:
   if float(r[col])==value:extremes.append({'region_code':r['region_code'],'province':r['province'],'region_name':r['region_name'],'variable':col,'value':value,'rule':label,'action':'retain'})
write(OUT/'tables/outlier_candidates.csv',flags)
write(OUT/'tables/extreme_regions.csv',extremes)

# 후보 지역을 스테이징 결과가 아닌 보존 원본에서 재구성한다.
candidates={r['region_code'] for r in flags+extremes}
crosswalk=read(ROOT/'data/reference/region_crosswalk.csv')
lookup={(r['dataset'],r['source_region_code']):r['region_code'] for r in crosswalk}
raw_election=read(ROOT/'data/raw/제21대 대통령선거 개표결과.csv','utf-8-sig')
votes=defaultdict(lambda:defaultdict(int))
for r in raw_election:
 key=r['시도명']+'|'+r['구시군명'];region=lookup[('election',key)]
 if region in candidates and r['후보자'] in ['선거인수','투표수']:votes[region][r['후보자']]+=int(r['득표수'])
raw_pop=read(ROOT/'data/raw/202505_202505_연령별인구현황_월간.csv','cp949')
pop={}
for r in raw_pop:
 code=re.search(r'\((\d{10})\)',r['행정구역'])[1]
 if ('population',code) in lookup and lookup[('population',code)] in candidates:
  region=lookup[('population',code)];ages=[int(r[f'2025년05월_계_{a}세'+(' 이상' if a==100 else '')].replace(',','')) for a in range(101)]
  pop[region]={'population_total':int(r['2025년05월_계_총인구수'].replace(',','')),
               'population_18plus':sum(ages[18:]),'population_65plus':sum(ages[65:]),'population_80plus':sum(ages[80:])}
raw_fiscal=json.loads((ROOT/'data/raw/lofin365_2025_A137_gov.json').read_text())['firFrsIxInqRsltDto']
fiscal={lookup[('fiscal',r['lafNm'])]:r['firRt'] for r in raw_fiscal if ('fiscal',r['lafNm']) in lookup}
with (ROOT/'data/raw/시군구별_이동자수_20261103170549.csv').open(encoding='cp949',newline='') as handle:migration_rows=list(csv.reader(handle))
net={lookup[('migration',r[0].split(' ',1)[0])]:int(r[3]) for r in migration_rows[2:] if ('migration',r[0].split(' ',1)[0]) in lookup}
midmap={r['source_region_code']:r['region_code'] for r in read(ROOT/'data/reference/midyear_region_crosswalk.csv') if r['region_code']}
with (ROOT/'data/raw/시군구_성_연령_1세_별_주민등록연앙인구_2023__20261103170428.csv').open(encoding='cp949',newline='') as handle:midrows=list(csv.reader(handle))
mid={midmap[r[0].split(' ',1)[0]]:Decimal(r[-1]) for r in midrows[1:] if r[0].split(' ',1)[0] in midmap}
spot=[]
for row in data:
 region=row['region_code']
 if region not in candidates:continue
 original={'electors':votes[region]['선거인수'],'voters':votes[region]['투표수'],**pop[region],
           'fiscal_independence':Decimal(fiscal[region]),'net_migrants':net[region],'midyear_population':mid[region]}
 for col,value in original.items():assert Decimal(row[col])==Decimal(value),(region,col)
 expected={'turnout':100*original['voters']/original['electors'],
           'aging_rate':100*original['population_65plus']/original['population_18plus'],
           'oldest_share':100*original['population_80plus']/original['population_65plus'],
           'net_migration_rate':Decimal(net[region])*100/mid[region],
           'log_population':math.log(original['population_total'])}
 for col,value in expected.items():assert equal(row[col],value),(region,col)
 reasons=[r['variable']+':'+r['rule'] for r in flags+extremes if r['region_code']==region]
 spot.append({'region_code':region,'province':row['province'],'region_name':row['region_name'],
              'reasons':';'.join(reasons),'source_numeric_fields_matched':14,'status':'raw_source_match',
              'decision':'retain','note':'same raw inputs; not independent official re-verification'})
write(OUT/'tables/source_spot_checks.csv',spot)
manifest=json.loads((OUT/'exploration_manifest.json').read_text())
artifacts={str((OUT/name).relative_to(OUT)):digest(OUT/name) for name in manifest['artifacts']}
for name in ['tables/outlier_candidates.csv','tables/extreme_regions.csv','tables/source_spot_checks.csv']:
 artifacts[name]=digest(OUT/name)
report={'status':'exploration_review_checks_passed','audit_code_sha256':digest(Path(__file__)),'dataset_sha256':manifest['dataset_sha256'],
        'observations':len(data),'missing_cells':sum(r[col]=='' for r in data for col in r),
        'descriptive_cells_independently_checked':checks,'statistic_tolerance':{'relative':1e-12,'absolute':1e-10},
        'pearson_absolute_tolerance':1e-12,'independent_pairs':independent_pairs,
        'candidate_rule':'six declared continuous variables; q(p) linear at (n-1)*p; strict outside Q1-1.5IQR/Q3+1.5IQR; core extrema also inspected',
        'iqr_thresholds':thresholds,'iqr_candidate_flags':len(flags),'unique_iqr_regions':len({r['region_code'] for r in flags}),
        'core_extreme_flags':len(extremes),'unique_regions_raw_rechecked':len(spot),
        'raw_numeric_fields_rechecked':len(spot)*14,'regions_removed':0,
        'source_recheck_is_independent_official_reverification':False,
        'regression_executed':False,'visual_review':'pending','artifacts':artifacts,
        'note':'Independent arithmetic implementation; raw-source checks reuse the same archived inputs.'}
(OUT/'exploration_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k not in ['artifacts','iqr_thresholds']},ensure_ascii=False,indent=2))
