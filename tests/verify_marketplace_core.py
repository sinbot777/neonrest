from pathlib import Path
import copy,csv,io,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from marketplace_core import *
checks=0
def check(v):
 global checks
 assert v
 checks+=1
def rejects(fn):
 try:fn()
 except InvalidCommerce:check(True)
 else:check(False)
q=quote(2000,500,125);check(q['platform_fee']==120);check(q['total']==2625);check(q['processor_fee'] is None);check(quote(2000,discount=1000)['platform_fee']==60);check(quote(9)['platform_fee']==1)
for val in (True,-1,1.2,'100',100_000_001):rejects(lambda:quote(val))
rejects(lambda:quote(100,shipping=10,kind='digital'));rejects(lambda:quote(100,discount=101))
check(commission_refund(1000,2000,120)==60);check(commission_refund(2000,2000,120,60)==60);check(commission_refund(2000,2000,120,120)==0);rejects(lambda:commission_refund(3000,2000,120))
p={'seller_id':1,'payment_status':'paid','kind':'physical','shipment_status':'unshipped','order_ref':'ord_A','shipment_ref':'shp_A','address':{'recipient':'Fictional Artist','line1':'1 Example Way','city':'Example','state':'MA','zip':'00123','country':'US'},'weight_oz':'4.5'}
raw=shipping_csv(1,[p]);r=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))[0];check(r['ZIP']=='00123');check(r['Weight Ounces']=='4.5');check(r['Length Inches']=='');check(b'email' not in raw)
for key,value in [('seller_id',2),('payment_status','pending'),('shipment_status','shipped'),('kind','digital')]:
 x=copy.deepcopy(p);x[key]=value;rejects(lambda:shipping_csv(1,[x]))
for bad in ('=HYPERLINK("bad")','+SUM(1)',' @bad','a\nformula'):
 x=copy.deepcopy(p);x['address']['recipient']=bad;rejects(lambda:shipping_csv(1,[x]))
x=copy.deepcopy(p);x['address']['zip']=123;rejects(lambda:shipping_csv(1,[x]));rejects(lambda:shipping_csv(1,[p,p]))
tracking=b'Order Reference,Shipment Reference,Carrier,Tracking Number\r\nord_A,shp_A,USPS,001234567890\r\n';known={('ord_A','shp_A'):p}
plan=tracking_preview(1,tracking,known);check(plan[0]['tracking']=='001234567890');check(plan[0]['action']=='set_tracking');rejects(lambda:tracking_preview(2,tracking,known));rejects(lambda:tracking_preview(1,tracking,{}));check(len(tracking_preview(1,tracking+b'ord_A,shp_A,USPS,001234567890\r\n',known))==1)
rejects(lambda:tracking_preview(1,tracking+b'ord_A,shp_A,UPS,OTHER123\r\n',known))
p['carrier']='USPS';p['tracking']='001234567890';p['shipment_status']='shipped';check(tracking_preview(1,tracking,known)[0]['action']=='unchanged')
rejects(lambda:tracking_preview(1,tracking.replace(b'001234567890',b'OTHER123'),known))
print(f'{checks} marketplace money/shipping checks passed')
