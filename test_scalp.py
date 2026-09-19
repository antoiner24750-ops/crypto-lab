import unittest, tempfile
from pathlib import Path
from unittest.mock import patch
import scalp_engine as e

def quote(side='LONG',price=None):
    rows=[[i*60,100,100.1,99.9,100,100,10] for i in range(22)]
    last=100.3 if side=='LONG' else 99.7
    rows[-1]=[1260,100,max(100.1,last+.05),min(99.9,last-.05),last,100,20]
    price=last if price is None else price
    return {'rows':rows,'bid':price-.005,'ask':price+.005,'mark':price}
def opened(side='LONG'):
    return e.step(e.initial(),{'BTC/EUR':quote(side)},1321)[0]
class TestEngine(unittest.TestCase):
    def test_directions(self):
        for side in ('LONG','SHORT'):
            s=opened(side);p=s['position'];self.assertEqual(p['side'],side)
            self.assertAlmostEqual(s['cash']+p['margin']+p['entry_fee'],200)
            price=p['entry']*(1.008 if side=='LONG' else .992)
            s,v=e.step(s,{'BTC/EUR':quote(side,price)},1330)
            self.assertIsNone(s['position']);self.assertGreater(s['trades'][-1]['net'],0)
            self.assertAlmostEqual(s['cash']-200,s['trades'][-1]['net'])
    def test_fees_and_timeout(self):
        s=opened();self.assertLess(e.valuation(s['position'],quote(),1321)['net'],0)
        s,v=e.step(s,{'BTC/EUR':quote()},2221)
        self.assertEqual(s['trades'][-1]['reason'],'15 minutes');self.assertEqual(s['gaps'],1)
        s,v=e.step(s,{'BTC/EUR':quote()},2222);self.assertIsNone(s['position'])
    def test_liquidation_both_sides(self):
        for side,price in [('LONG',80),('SHORT',120)]:
            s=opened(side);s,v=e.step(s,{'BTC/EUR':quote(side,price)},1330)
            t=s['trades'][-1];self.assertEqual(t['reason'],'liquidation simulée')
            self.assertAlmostEqual(t['net'],-20.1);self.assertGreater(t['floor_adjustment'],0)
    def test_drawdown_halts(self):
        s=e.initial();s['cash']=175
        s,v=e.step(s,{'BTC/EUR':quote()},1321);self.assertIsNone(s['position'])
    def test_stale_and_missing_bars(self):
        e.check_rows(quote()['rows'],1321)
        with self.assertRaises(ValueError):e.check_rows(quote()['rows'],1500)
        rows=quote()['rows'];rows[-2][0]-=60
        with self.assertRaises(ValueError):e.check_rows(rows,1321)
    def test_persistence_corruption(self):
        with tempfile.TemporaryDirectory() as td,patch.object(e,'FILE',Path(td)/'state.json'):
            s=opened();e.save(s);self.assertEqual(e.load(),s)
            e.FILE.write_text('{broken')
            with self.assertRaises(ValueError):e.load()
if __name__=='__main__':unittest.main()
