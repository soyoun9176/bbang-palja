"""Server-only dice faces. Public metadata intentionally omits odds and price bands."""

DICE = {
    'walkin': {'name': '현장 구매 주사위', 'color': 'plain', 'faces': (1, 2, 3, 3, 4, 5)},
    'preorder_plain': {'name': '준비된 마법사의 주사위', 'color': 'plain', 'faces': (1, 2, 3, 4, 5, 6)},
    'preorder_rainbow': {'name': '준비된 마법사의 주사위', 'color': 'rainbow', 'faces': (2, 2, 3, 5, 6, 12)},
    'preorder_silver': {'name': '준비된 마법사의 주사위', 'color': 'silver', 'faces': (3, 5, 7, 9, 11, 18)},
    'preorder_gold': {'name': '준비된 마법사의 주사위', 'color': 'gold', 'faces': ('milk', 6, 9, 11, 15, 22)},
    'instagram': {'name': '인싸 마법사의 주사위', 'color': 'pink', 'faces': (1, 1, 2, 2, 3, 'milk')},
}

MILESTONES = (
    {'threshold': 5, 'kind': 'oatmeal', 'name': '오트밀 미니바이트', 'extra': '프로필 배지 1 · 추후 추가'},
    {'threshold': 10, 'kind': 'milk', 'name': '우유', 'extra': '프로필 배지 2 · 추후 추가'},
    {'threshold': 15, 'kind': 'sunglasses', 'name': '멋진 선글라스', 'extra': '칭호 「멋쟁이 마법사」 · 추후 추가'},
    {'threshold': 20, 'kind': 'bread', 'name': '랜덤 빵 1개', 'extra': ''},
    {'threshold': 30, 'kind': 'bread', 'name': '랜덤 빵 1개', 'extra': '담당자가 지어주는 커스텀 칭호 · 추후 추가'},
)


def public_dice(kind):
    return {'kind': kind, **{key: DICE[kind][key] for key in ('name', 'color')}}


def preorder_kind(total):
    if total <= 5000:
        return 'preorder_plain'
    if total <= 10000:
        return 'preorder_rainbow'
    if total <= 20000:
        return 'preorder_silver'
    return 'preorder_gold'
