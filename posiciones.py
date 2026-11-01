"""Tus posiciones del plan de compras (plan_compras.json): que compras se ejecutaron, precio promedio, liquidacion,
ganancia/perdida, apalancamiento real, niveles de toma de ganancias y cuanto se puede sumar al piramidar.
La pagina hace las mismas cuentas (dashboard/index.html, planEstado). Margen aislado: el margen extra ya agregado
esta en la posicion aunque su compra no se haya ejecutado todavia."""


def mmr(plan, m):
    mt = plan.get("mantenimiento") or {}
    return mt.get(m, mt.get("otras", 0.01))


def liquidacion(nocional, cantidad, margen, r):
    """Precio de liquidacion de un long aislado: el margen mas la ganancia llega al mantenimiento."""
    return max(0.0, (nocional - margen) / (cantidad * (1 - r))) if cantidad > 0 else None


def estado(plan, m, bajo, alto, precio):
    """Estado de una cripto del plan. bajo / alto: minimo y maximo desde plan["desde"]; precio: el de ahora."""
    lev = plan.get("apalancamiento", 5)
    cs = [c for c in plan["compras"] if c["moneda"] == m]
    hechas = [c for c in cs if c.get("cargada") and bajo is not None and bajo <= c["precio"]]
    margen = sum(c["orden"] / lev for c in hechas) + sum(c["extra"] for c in cs if c.get("extra_agregado"))
    nocional = sum(c["orden"] for c in hechas)
    cantidad = sum(c["orden"] / c["precio"] for c in hechas)
    r = mmr(plan, m)
    out = {"moneda": m, "hechas": len(hechas), "total": len(cs), "precio": precio, "margen": margen,
           "pendientes": [c for c in cs if c not in hechas]}
    if not hechas:
        return out
    prom = nocional / cantidad
    valor = cantidad * precio
    liq = liquidacion(nocional, cantidad, margen, r)
    out.update(promedio=prom, cantidad=cantidad, nocional=nocional, valor=valor, pnl=valor - nocional,
               pnl_pct=(valor - nocional) / margen * 100, apalancamiento_real=valor / (margen + valor - nocional),
               liquidacion=liq, dist_liq=(precio / liq - 1) * 100 if liq else None)
    g = plan.get("ganancias") or {}
    if g:
        out["ganancias"] = [{"k": k, "precio": prom * (1 + g["cada"] * k), "vender": cantidad * g["vender"],
                             "usdt": cantidad * g["vender"] * prom * (1 + g["cada"] * k),
                             "alcanzado": alto is not None and alto >= prom * (1 + g["cada"] * k)}
                            for k in range(1, g.get("niveles", 4) + 1)]
    pz = plan.get("piramidar") or {}
    if pz:
        lmax = pz["liq_max"] * min(c["precio"] for c in cs)
        k = lmax * (1 - r)
        a = (k * cantidad - nocional + margen) / (1 - k / precio) if precio > k else 0.0   # que la liq no pase lmax
        a = max(0.0, min(a, lev * margen - nocional))                                     # y que alcance el margen
        out["piramidar"] = {"disponible": precio >= prom * (1 + pz["cada"]), "desde": prom * (1 + pz["cada"]),
                            "sumar": a, "monedas": a / precio,
                            "liq_nueva": liquidacion(nocional + a, cantidad + a / precio, margen, r), "liq_max": lmax}
    return out
