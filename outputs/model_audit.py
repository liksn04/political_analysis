"""실제 결과의 독립 행렬 재계산. 생산 추정 함수/설계행렬을 재사용하지 않는다."""
import csv,hashlib,json,math
from pathlib import Path
from statistics import NormalDist
import numpy as np
import pandas as pd
from political_analysis.pipeline import verify_dataset_certificate

ROOT=Path(__file__).resolve().parent.parent
OUT=ROOT/'outputs'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
quality=verify_dataset_certificate(ROOT/'data/processed/analysis_dataset.csv',OUT/'data_quality.json')
manifest=json.loads((OUT/'model_manifest.json').read_text())
assert manifest['dataset_sha256']==quality['dataset_sha256']
assert manifest['quality_sha256']==digest(OUT/'data_quality.json')
assert manifest['model_code_sha256']==digest(ROOT/'src/political_analysis/models.py')
for name,sha in manifest['artifacts'].items():assert digest(OUT/name)==sha
frame=pd.read_csv(ROOT/'data/processed/analysis_dataset.csv',dtype={'region_code':str})
coef=pd.read_csv(OUT/'tables/model_coefficients.csv')
summary=pd.read_csv(OUT/'tables/model_summary.csv')
samples=pd.read_csv(OUT/'tables/model_samples.csv',dtype={'sample_id':str})
# 검증 계약의 변수를 명시하고 생산 모형의 상수를 참조하지 않는다.
variables={'M1':['aging_rate'],'M2':['aging_rate','oldest_share'],
           'M3':['aging_rate','oldest_share','fiscal_independence','net_migration_rate','log_population'],
           'M4':['aging_rate','oldest_share','fiscal_independence','net_migration_rate','log_population']}
fields=['estimate','std_error_hc3','p_value','ci_low','ci_high']
errors={name:0. for name in fields};cells=0;models=[];z=NormalDist().inv_cdf(.975)
for row in summary.to_dict('records'):
 name=row['model'];base=name.split('_')[0];weighted=name=='M4_WLS';common=name.endswith('_common')
 required=['turnout']+variables['M4' if common else base]
 if base=='M4' or common:required+=['region_type','province']
 if weighted:required+=['electors']
 mask=frame[required].notna().all(axis=1)
 if base=='M4' or common:mask &= frame.region_type.ne('특수지역')
 part=frame.loc[mask]
 columns={'Intercept':np.ones(len(part))}
 columns.update({v:part[v].to_numpy(float) for v in variables[base]})
 if base=='M4':
  for factor in ['region_type','province']:
   levels=sorted(part[factor].unique())
   assert row[factor+'_reference']==levels[0]
   for level in levels[1:]:columns[f'C({factor})[T.{level}]']=part[factor].eq(level).to_numpy(float)
 names=list(columns);x=np.column_stack(list(columns.values()));y=part.turnout.to_numpy(float)
 weights=part.electors.to_numpy(float) if weighted else np.ones(len(part))
 xw=x*np.sqrt(weights)[:,None];yw=y*np.sqrt(weights)
 bread=np.linalg.inv(xw.T@xw);b=np.linalg.solve(xw.T@xw,xw.T@yw)
 error=yw-xw@b;hat=np.einsum('ij,jk,ik->i',xw,bread,xw)
 covariance=bread @ (xw.T @ ((error/(1-hat))[:,None]**2*xw)) @ bread
 se=np.sqrt(np.diag(covariance));p=np.array([math.erfc(abs(a/s)/math.sqrt(2)) for a,s in zip(b,se)])
 expected=pd.DataFrame({'estimate':b,'std_error_hc3':se,'p_value':p,'ci_low':b-z*se,'ci_high':b+z*se},index=names)
 actual=coef.loc[coef.model==name].set_index('term');assert set(actual.index)==set(names)
 for field in fields:
  np.testing.assert_allclose(actual.loc[names,field],expected[field],rtol=1e-8,atol=1e-9)
  errors[field]=max(errors[field],float(np.max(abs(actual.loc[names,field]-expected[field]))));cells+=len(names)
 membership=samples.loc[samples.model==name]
 assert len(membership)==len(frame) and not membership.sample_id.duplicated().any()
 assert membership.loc[membership.included,'sample_id'].tolist()==part.region_code.tolist()
 assert membership.included.tolist()==mask.tolist()
 assert membership.loc[membership.included,'exclusion_reason'].isna().all()
 for excluded in membership.loc[~membership.included].to_dict('records'):
  expected_reason=('outside_M4_common_sample;' if common else '')+'special_region_policy'
  assert excluded['region_type']=='특수지역' and excluded['exclusion_reason']==expected_reason
 assert row['n']==len(part) and row['parameters']==len(names)==row['design_rank']
 assert row['df_resid']==len(part)-len(names) and row['ci_distribution']=='normal'
 assert set(json.loads(row['design_columns']))==set(names)
 np.testing.assert_allclose([row['max_leverage'],row['condition_number']],[max(hat),np.linalg.cond(xw)],rtol=1e-8,atol=1e-9)
 r2=1-np.sum(error**2)/np.sum(weights*(y-np.average(y,weights=weights))**2)
 np.testing.assert_allclose([row['r_squared'],row['adj_r_squared']],[r2,1-(1-r2)*(len(part)-1)/(len(part)-len(names))],rtol=1e-10,atol=1e-10)
 models.append({'model':name,'n':len(part),'parameters':len(names),'df_resid':len(part)-len(names),'sample_verified':True})
ids={name:set(g.loc[g.included,'sample_id']) for name,g in samples.groupby('model')}
assert ids['M4']==ids['M4_WLS']==ids['M1_common']==ids['M2_common']==ids['M3_common']
assert set(frame.region_code)-ids['M4']=={'3600000000','5000000000'}
# make analyze가 재생성한 탐색 산출물도 기존 검수 해시와 일치해야 한다.
explore=json.loads((OUT/'exploration_manifest.json').read_text());review=json.loads((OUT/'exploration_validation.json').read_text())
for name,sha in {**explore['artifacts'],**review['artifacts']}.items():assert digest(OUT/name)==sha
verdicts=[]
for name in ['M1','M2','M3','M4']:
 for term,hypothesis,direction in [('aging_rate','H1',1),('oldest_share','H2',-1)]:
  selected=coef.loc[(coef.model==name)&(coef.term==term)]
  if selected.empty:continue
  r=selected.iloc[0];excludes_zero=r.ci_low>0 or r.ci_high<0
  predicted=r.estimate*direction>0
  status=('directional_evidence' if predicted else 'opposite_direction_evidence') if excludes_zero else 'direction_uncertain'
  verdicts.append({'model':name,'hypothesis':hypothesis,'term':term,'estimate':float(r.estimate),
                   'std_error_hc3':float(r.std_error_hc3),'p_value':float(r.p_value),
                   'ci_low':float(r.ci_low),'ci_high':float(r.ci_high),
                   'n':int(summary.set_index('model').loc[name,'n']),'ci_excludes_zero':bool(excludes_zero),
                   'verdict':status})
with (OUT/'tables/hypothesis_evaluation.csv').open('w',newline='') as f:
 writer=csv.DictWriter(f,fieldnames=list(verdicts[0]));writer.writeheader();writer.writerows(verdicts)
report={'status':'actual_model_outputs_independently_checked','dataset_sha256':quality['dataset_sha256'],
        'audit_code_sha256':digest(Path(__file__)),'model_code_sha256':manifest['model_code_sha256'],
        'coefficient_cells_checked':cells,'sample_membership_rows_checked':len(samples),
        'coefficient_tolerance':{'relative':1e-8,'absolute':1e-9},'maximum_absolute_errors':errors,
        'models':models,'ci_distribution':'normal','actual_research_regression_executed':True,
        'exploration_artifacts_preserved':True,'source_reconciliation_adjustment_is_independent':False,
        'robustness_review_complete':False,'text_review':'pending','hypothesis_verdicts':verdicts,
        'artifacts':{name:digest(OUT/name) for name in ['model_manifest.json','tables/model_coefficients.csv','tables/model_summary.csv','tables/model_samples.csv','tables/hypothesis_evaluation.csv','model_notes.txt']}}
(OUT/'model_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k not in ['artifacts','hypothesis_verdicts']},ensure_ascii=False,indent=2))
