import datetime

# Валюта ивента (назовем её "Жетон Механика" или просто "Жетоны")
EVENT_NAME = "Операция «Наследие»"
EVENT_CURRENCY = "Жетоны Наследия"

# Танк, который является главной наградой
MAIN_REWARD_TANK = "Pz.Kpfw. VII"

# Всего жетонов для получения ГЛАВНОЙ награды
TOTAL_TOKENS_FOR_MAIN = 255

# Цепочка наград. 
# Чтобы получить главную, надо собрать ВСЕ награды по цепочке (сумма цен = 255)
EVENT_REWARDS = [
    {"id": 1, "name": "2000 XP", "cost": 20, "type": "xp", "value": 2000},
    {"id": 2, "name": "Контейнер (шанс танка)", "cost": 35, "type": "container", "value": "premium"},
    {"id": 3, "name": "3000 XP", "cost": 45, "type": "xp", "value": 3000},
    {"id": 4, "name": "Контейнер (шанс танка)", "cost": 55, "type": "container", "value": "premium"},
    {"id": 5, "name": "5000 XP", "cost": 100, "type": "xp", "value": 5000},
    {"id": 6, "name": "Pz.Kpfw. VII", "cost": 0, "type": "tank", "value": "Pz.Kpfw. VII"} # Главная награда (выдается после предыдущих)
]

# Сумма всех cost = 255. (20+35+45+55+100 = 255). Шестая награда бесплатно, так как сумма собрана.
TOTAL_COST = sum(r["cost"] for r in EVENT_REWARDS[:-1])

# Даты ивента (поставим 25 дней от текущего момента)
START_DATE = datetime.datetime.now()
END_DATE = START_DATE + datetime.timedelta(days=25)

# Награды за бой (сколько дают валюты в зависимости от эффективности)
# Эффективность (урон) -> Валюта
def get_tokens_for_battle(win: bool, damage: int) -> int:
    # Если проиграл, но нанес урон, может дать 0-1. Если выиграл, 1-3.
    if win:
        if damage > 1000: return 3
        elif damage > 500: return 2
        else: return 1
    else:
        if damage > 1000: return 1
        return 0
