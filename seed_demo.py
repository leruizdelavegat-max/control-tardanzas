"""Carga datos ficticios para probar la aplicación localmente.

Uso:  DATABASE_URL=sqlite:///demo.db python seed_demo.py
Por seguridad se niega a ejecutarse contra una base que no sea SQLite.
"""

import random
from datetime import time, timedelta

import database as db
import payments
import tardiness
from config import PAYMENT_METHODS, today_lima

NAMES = ["Ana Torres", "Pedro Salas", "María Quispe", "Luis Ramírez", "Sofía Medina", "Diego Huamán",
         "Valeria Rojas", "Jorge Castillo", "Camila Flores", "Renato Vargas"]
ACTIVITIES = ["Reunión general", "Campaña de reciclaje", "Taller de liderazgo", "Visita al albergue"]


def main() -> None:
    if not db.get_engine().url.drivername.startswith("sqlite"):
        raise SystemExit("seed_demo.py solo se ejecuta con SQLite, para no ensuciar la base real.")
    rng = random.Random(42)
    today = today_lima()
    for weeks_ago in range(16, 0, -1):
        day = today - timedelta(weeks=weeks_ago, days=today.weekday() - 5)  # sábados
        name = ACTIVITIES[weeks_ago % len(ACTIVITIES)]
        act_id, *_ = tardiness.get_or_create_activity(name, day, time(9, 0))
        for person in rng.sample(NAMES, rng.randint(2, 5)):
            arrival = time(9, rng.choice([3, 8, 10, 12, 15, 19, 20, 22, 25, 30, 35, 41]))
            if arrival.minute == 0:
                continue
            res = tardiness.register_tardy(act_id, person, arrival)
            if weeks_ago > 3 and rng.random() < 0.7:
                pay_day = min(day + timedelta(days=rng.randint(1, 10)), today)
                payments.register_payment(res["id"], pay_day, res["penalty"], rng.choice(PAYMENT_METHODS))
    print("Datos de demostración cargados.")


if __name__ == "__main__":
    main()
