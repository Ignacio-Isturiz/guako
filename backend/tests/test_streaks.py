from datetime import date, timedelta

from app.streaks import StreakData, current_count, recoveries_left, register_activity, status

D = date(2026, 11, 10)


def day(n: int) -> date:
    return D + timedelta(days=n)


def test_primera_actividad_empieza_la_racha() -> None:
    s = StreakData()
    assert status(s, day(0)) == "none"
    assert register_activity(s, day(0)) is False
    assert (s.current, s.best, status(s, day(0))) == (1, 1, "done")


def test_un_dia_cuenta_una_sola_vez() -> None:
    s = StreakData()
    register_activity(s, day(0))
    register_activity(s, day(0))
    assert s.current == 1


def test_dias_seguidos_suman() -> None:
    s = StreakData()
    for n in range(4):
        register_activity(s, day(n))
    assert s.current == 4
    assert status(s, day(4)) == "pending"  # vive, falta hacerla hoy


def test_falla_un_dia_y_lo_recupera_al_siguiente() -> None:
    s = StreakData()
    for n in range(3):
        register_activity(s, day(n))  # racha 3, último día = day(2)
    # day(3) se pierde; en day(4) tiene la oportunidad
    assert status(s, day(4)) == "recoverable"
    assert current_count(s, day(4)) == 3  # todavía se ve la racha
    assert register_activity(s, day(4)) is True
    assert s.current == 4
    assert recoveries_left(s, day(4)) == 2


def test_si_no_aprovecha_la_oportunidad_se_acaba_y_no_gasta_nada() -> None:
    s = StreakData()
    for n in range(3):
        register_activity(s, day(n))
    assert status(s, day(5)) == "none"  # falló day(3) y day(4)
    assert current_count(s, day(5)) == 0
    assert register_activity(s, day(5)) is False
    assert s.current == 1
    assert s.best == 3  # la mejor racha se conserva
    assert recoveries_left(s, day(5)) == 3


def test_solo_hay_tres_oportunidades_por_mes() -> None:
    s = StreakData()
    register_activity(s, day(0))
    today = day(0)
    for _ in range(3):  # falla un día, recupera, tres veces
        today += timedelta(days=2)
        assert register_activity(s, today) is True
    assert recoveries_left(s, today) == 0
    # 4.ª vez en el mismo mes: ya no puede recuperar
    today += timedelta(days=2)
    assert today.month == D.month
    assert status(s, today) == "none"
    register_activity(s, today)
    assert s.current == 1


def test_las_oportunidades_se_renuevan_cada_mes_sin_acumularse() -> None:
    s = StreakData(current=5, best=5, last_day=date(2026, 11, 28), recoveries_used=3, recoveries_month="2026-11")
    assert recoveries_left(s, date(2026, 11, 30)) == 0
    # falla el 29, recupera el 30 (aún noviembre): sin oportunidades → se acabó
    assert status(s, date(2026, 11, 30)) == "none"
    # otro caso: último día 30-nov, falla 1-dic, recupera 2-dic con mes nuevo → 3 oportunidades
    s = StreakData(current=5, best=5, last_day=date(2026, 11, 30), recoveries_used=3, recoveries_month="2026-11")
    assert recoveries_left(s, date(2026, 12, 2)) == 3
    assert register_activity(s, date(2026, 12, 2)) is True
    assert (s.current, s.recoveries_used, s.recoveries_month) == (6, 1, "2026-12")


def test_mes_sin_usar_no_acumula_mas_de_tres() -> None:
    s = StreakData(current=2, best=2, last_day=date(2026, 12, 1))
    assert recoveries_left(s, date(2026, 12, 3)) == 3
