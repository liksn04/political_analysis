from pathlib import Path
import hashlib,json,numpy as np,pandas as pd
root=Path(__file__).resolve().parent
checkout=root/'checkout'; generated=root/'generated-evidence'
result=json.loads((checkout/'outputs/reproduction/operator_replay_result.json').read_text())
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
metrics={}
for relative,entry in result['output_comparisons'].items():
    baseline=checkout/relative; replay=generated/relative
    assert sha(baseline)==entry['baseline_sha256']
    assert sha(replay)==entry['replay_sha256']
    record={'baseline_sha256':sha(baseline),'generated_sha256':sha(replay),'byte_identical':baseline.read_bytes()==replay.read_bytes()}
    if replay.suffix=='.csv':
        a=pd.read_csv(baseline);b=pd.read_csv(replay)
        pd.testing.assert_frame_equal(a,b,check_exact=True)
        numeric=a.select_dtypes(include='number').columns
        finite=np.isfinite(a[numeric].to_numpy(dtype=float))
        difference=np.abs(a[numeric].to_numpy(dtype=float)-b[numeric].to_numpy(dtype=float))
        record.update(rows=len(a),numeric_columns=len(numeric),finite_numeric_cells=int(finite.sum()),maximum_absolute_difference=float(difference[finite].max()) if finite.any() else 0.0)
    metrics[relative]=record
for relative,digest in result['identical_stage_dataset_reconciliation'].items():
    assert sha(generated/relative)==digest==sha(checkout/relative)
summary={'operator_result_sha256':sha(checkout/'outputs/reproduction/operator_replay_result.json'),'tables':sum(p.endswith('.csv') for p in metrics),'figures':sum(p.endswith('.png') for p in metrics),'finite_numeric_cells':sum(r.get('finite_numeric_cells',0) for r in metrics.values()),'maximum_absolute_difference':max(r.get('maximum_absolute_difference',0) for r in metrics.values()),'byte_difference_count':sum(not r['byte_identical'] for r in metrics.values()),'files':metrics}
(root/'postcheck.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in summary.items() if k!='files'},indent=2))
