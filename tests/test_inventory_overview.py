"""Staff item totals distinguish all preorders, completed sales, gifts and holds."""
import os
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch

from server.app import APIError, Application, now


class InventoryOverviewTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='cambo-inventory-overview-')
        self.addCleanup(folder.cleanup)
        env = patch.dict(os.environ, DB_PATH=str(Path(folder.name)/'app.sqlite3'), DATABASE_URL='',
                         APP_ENV='production', DEMO_SEED='0', STAFF_PASSWORD='inventory-test')
        env.start()
        self.addCleanup(env.stop)
        self.app = Application()
        self.staff = self.api('/api/staff/login', {'name':'담당','password':'inventory-test'})['token']
        self.serial = 0
        self.buyer = self.register()
        with self.app.db.transaction(write=True) as tx:
            tx.execute('UPDATE products SET stock=100 WHERE id IN (101,102,112,113)')

    def api(self, path, body=None, token=None, *, method='POST', query=None):
        return self.app.handle(method, path, query or {}, body or {}, 'Bearer '+token if token else None)

    def register(self):
        self.serial += 1
        return self.api('/api/auth/register', {'name':'테스트','phone':f'010-9999-{self.serial:04}','pin':'1234'})

    def dashboard(self):
        return self.api('/api/staff/dashboard', token=self.staff, method='GET')

    def summary(self, pid=101):
        return next(row for row in self.dashboard()['inventory_summary'] if row['product_id']==pid)

    def order(self, quantity):
        return self.api('/api/orders', {'items':[{'product_id':101,'quantity':quantity}],
                                       'request_id':uuid.uuid4().hex}, self.buyer['token'])['order']

    def transition(self, order, action):
        return self.api(f"/api/staff/orders/{order['id']}/{action}", {}, self.staff)['order']

    def test_preorder_total_includes_unclaimed_pending_and_completed_without_counting_as_walkin(self):
        source = [{'name':f'예약{i}','phone':f'010-8000-{i:04}',
                   'items':[{'product_id':101,'quantity':quantity}]} for i,quantity in enumerate((2,3,4))]
        self.api('/api/staff/preorders/import', {'reservations':source}, self.staff)
        bookings = sorted(self.dashboard()['reservations'], key=lambda r:r['id'])
        orders = []
        for booking in bookings[1:]:
            self.api('/api/preorders/lookup', token=self.buyer['token'], method='GET',
                     query={'name':[booking['name']],'phone':[booking['phone']]})
            orders.append(self.api(f"/api/preorders/{booking['id']}/claim", {'request_id':uuid.uuid4().hex}, self.buyer['token'])['order'])
        self.transition(orders[1], 'approve')
        row = self.summary()
        self.assertEqual((row['preorder_sold'],row['walkin_sold'],row['event_given'],row['held'],row['remaining']), (9,0,0,3,94))
        self.transition(orders[0], 'cancel')
        self.transition(orders[0], 'cancel')
        row = self.summary()
        self.assertEqual((row['preorder_sold'],row['held'],row['remaining']), (9,0,91))

    def test_walkin_and_guest_manual_sales_count_only_after_approval_and_holds_are_still_remaining(self):
        approved = self.order(2)
        self.transition(approved, 'approve')
        self.transition(approved, 'approve')
        self.api('/api/staff/manual-sale', {'guest':True,'name':'비회원','items':[{'product_id':101,'quantity':4}],
                                          'request_id':uuid.uuid4().hex}, self.staff)
        pending = self.order(3)
        cancelled = self.order(5)
        self.transition(cancelled, 'cancel')
        row = self.summary()
        self.assertEqual((row['preorder_sold'],row['walkin_sold'],row['event_given'],row['held'],row['remaining']), (0,6,0,3,94))
        self.transition(pending, 'approve')
        row = self.summary()
        self.assertEqual((row['walkin_sold'],row['held'],row['remaining']), (9,0,91))

    def test_event_totals_include_manual_and_legacy_bread_without_double_counting_or_cancelled_gifts(self):
        other = self.register()
        with self.app.db.transaction(write=True) as tx:
            for uid,threshold,status in ((self.buyer['user']['id'],20,'approved'),(self.buyer['user']['id'],30,'pending'),
                                         (other['user']['id'],20,'cancelled'),(other['user']['id'],30,None)):
                claim = tx.insert("INSERT INTO milestone_claims(user_id,threshold,kind,product_id,product_name,created_at) VALUES(?,?,'bread',101,'빵',?)",(uid,threshold,now()))
                if status:
                    tx.insert("INSERT INTO reward_requests(user_id,milestone_id,kind,status,product_id,product_name,created_at) VALUES(?,?,'bread',?,101,'빵',?)",(uid,claim,status,now()))
            tx.insert("INSERT INTO rewards(user_id,product_id,product_name,threshold,created_at) VALUES(?,101,'이전 보상',10,?)",(self.buyer['user']['id'],now()))
        self.api('/api/staff/manual-event-grants', {'guest':True,'name':'현장 지급','kind':'bread','product_id':101,
            'quantity':3,'reason':'점검','request_id':uuid.uuid4().hex}, self.staff)
        with self.app.db.transaction(write=True) as tx:
            tx.execute('UPDATE products SET stock=40 WHERE id=101')
        row = self.summary()
        self.assertEqual((row['walkin_sold'],row['event_given'],row['held'],row['remaining']), (0,6,1,41))
        self.assertEqual(self.dashboard()['stats']['bread_event_given'],6)

    def test_milk_and_soymilk_include_legacy_awards_but_not_declines_pending_or_fallback_dice(self):
        uid = self.buyer['user']['id']
        with self.app.db.transaction(write=True) as tx:
            for status,pid,fallback in (('approved',112,None),('pending',113,None),('cancelled',112,None),
                                        ('approved',None,'walkin'),('awaiting_choice',None,None),(None,None,None)):
                roll = tx.insert("INSERT INTO typed_dice_rolls(user_id,kind,result,value,created_at) VALUES(?,'instagram','milk',0,?)",(uid,now()))
                if status:
                    tx.insert("INSERT INTO reward_requests(user_id,roll_id,kind,status,product_id,product_name,created_at,fallback_dice_kind) VALUES(?,?,'milk',?,?,'음료',?,?)",(uid,roll,status,pid,now(),fallback))
            tx.insert("INSERT INTO milestone_claims(user_id,threshold,kind,product_id,product_name,created_at) VALUES(?,10,'milk',113,'두유',?)",(uid,now()))
            tx.insert("INSERT INTO events(user_id,customer_name,type,milk_quantity,dice,created_at) VALUES(?,'과거 참가자','instagram',2,0,?)",(uid,now()))
        for gift,quantity in (('milk',3),('soymilk',2)):
            self.api('/api/staff/event-beverage-limits', {'product_id':112 if gift=='milk' else 113,'limit':100,'request_id':uuid.uuid4().hex}, self.staff)
            self.api('/api/staff/manual-event-grants', {'guest':True,'name':'음료 지급','kind':'gift','gift':gift,
                'quantity':quantity,'reason':'점검','request_id':uuid.uuid4().hex}, self.staff)
        self.assertEqual((self.summary(112)['event_given'],self.summary(113)['event_given']), (7,3))
        self.assertEqual((self.summary(112)['held'],self.summary(113)['held']), (0,1))

    def test_summary_includes_pending_orders_and_sales_outside_dashboard_history(self):
        uid = self.buyer['user']['id']
        with self.app.db.transaction(write=True) as tx:
            for index in range(501):
                quantity, status = (7,'pending') if index==0 else (1,'approved')
                oid = tx.insert("INSERT INTO orders(user_id,customer_name,type,status,total,quantity,created_at) VALUES(?,'과거 주문','walkin',?,?,?,?)",(uid,status,quantity*2800,quantity,now()))
                tx.insert("INSERT INTO order_items(order_id,product_id,name,quantity,price) VALUES(?,101,'빵',?,2800)",(oid,quantity))
            tx.execute('UPDATE products SET stock=22 WHERE id=101')
        dashboard = self.dashboard()
        self.assertEqual(len(dashboard['orders']),500)
        self.assertFalse(any(row['status']=='pending' for row in dashboard['orders']))
        row = next(row for row in dashboard['inventory_summary'] if row['product_id']==101)
        self.assertEqual((row['walkin_sold'],row['held'],row['remaining']), (500,7,29))

    def test_zero_totals_are_staff_only_and_do_not_expose_purchase_history_in_products(self):
        self.assertEqual(self.summary(110),{'product_id':110,'preorder_sold':0,'walkin_sold':0,'event_given':0,'held':0,'remaining':0})
        with self.assertRaises(APIError) as error:
            self.api('/api/staff/dashboard', token=self.buyer['token'], method='GET')
        self.assertEqual(error.exception.status,403)
        products = self.api('/api/products',method='GET')['products']
        self.assertTrue(all('preorder_sold' not in row and 'walkin_sold' not in row and 'event_given' not in row for row in products))


if __name__ == '__main__':
    unittest.main()
