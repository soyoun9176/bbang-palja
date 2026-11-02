"""Event menu. Stable IDs keep previous prototype orders and reservations intact."""

# id, real name, concept name, KRW, demo walk-in, reserved, demo reward, category, icon
PRODUCTS = [
    (101, '플레인 휘낭시에', '바람의 정수', 2800, 20, 0, 3, '휘낭시에', 'wind'),
    (102, '초코 휘낭시에', '흙의 정수', 3000, 20, 0, 3, '휘낭시에', 'earth'),
    (103, '카라멜 휘낭시에', '불의 정수', 3000, 20, 0, 3, '휘낭시에', 'fire'),
    (104, '무화과 휘낭시에', '물의 정수', 3400, 20, 0, 3, '휘낭시에', 'water'),
    (105, '로투스 브라우니 치즈케이크', '고대 마법서', 3800, 20, 0, 3, '케이크', 'grimoire'),
    (106, '레몬 다쿠아즈', '빛의 결실', 3500, 20, 0, 3, '다쿠아즈', 'light'),
    (107, '얼그레이 다쿠아즈', '현자의 돌', 3500, 20, 0, 3, '다쿠아즈', 'stone'),
    (108, '글레이즈드 도넛 5개 세트', '구슬', 2000, 20, 0, 3, '도넛', 'orbs'),
    (109, '보늬밤 마들렌', '신성한 나무의 열매', 2800, 20, 0, 3, '마들렌', 'sacred-fruit'),
    (110, '에그타르트', '황금이 들어있는 용광로', 2800, 20, 0, 3, '타르트', 'furnace'),
    (111, '치즈타르트', '황금이 들어있는 용광로', 2800, 20, 0, 3, '타르트', 'furnace'),
]
PRODUCT_IDS = tuple(product[0] for product in PRODUCTS)
PRODUCT_UNITS = {108: '세트'}


def sync_catalog(tx, demo=False):
    """Add missing menu rows; update labels/prices while preserving all inventory."""
    added = 0
    for product in PRODUCTS:
        if tx.one('SELECT id FROM products WHERE id = ?', (product[0],)):
            tx.execute('UPDATE products SET name=?,subtitle=?,price=?,category=?,image=? WHERE id=?',
                       (product[1], product[2], product[3], product[7], product[8], product[0]))
        else:
            initial = product if demo else (*product[:4], 0, 0, 0, *product[7:])
            tx.execute('INSERT INTO products (id,name,subtitle,price,stock,preorder_stock,reward_stock,category,image) VALUES (?,?,?,?,?,?,?,?,?)', initial)
            added += 1
    return added
