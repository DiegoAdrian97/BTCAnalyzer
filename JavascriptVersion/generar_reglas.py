"""Copia a api/contexto.js las reglas de noticias de noticias.py (acciones, temas y si cada titular es bueno o malo),
para que Python y JavaScript usen exactamente los mismos patrones. Correr despues de cambiar noticias.py:
    python JavascriptVersion/generar_reglas.py
pruebas/sesgo.py verifica que den lo mismo."""
import json, os, sys
AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(AQUI))
import noticias as n  # noqa: E402

NOMBRES = ["BOLSA", "CHINA", "CHINA_SOLO", "EEUU", "EEUU_SOLO", "LATAM", "LATAM_SOLO", "ECON", "CHIPS_IA", "TEC_IA",
           "SUBE", "BAJA", "COMPARA_SUBE", "COMPARA_BAJA", "MALO_SI_SUBE", "CONTRASTE", "PARTES", "SUJETO_BTC",
           "SUJETO_BOLSA", "SECTOR_AMPLIO", "FUERTE_BUENO", "FUERTE_MALO", "FUERTE_BTC_BUENO", "FUERTE_BTC_MALO",
           "FUERTE_ACCION_BUENO", "FUERTE_ACCION_MALO", "PALABRA_BUENA", "PALABRA_MALA", "ACCIONES", "IMPACTO"]
INI, FIN = "// ---- reglas copiadas de noticias.py (generar_reglas.py): no editar a mano ----", "// ---- fin de las reglas copiadas ----"
bloque = [INI] + [f"const {k} = {json.dumps(getattr(n, k), ensure_ascii=False)};" for k in NOMBRES] + [FIN]
p = os.path.join(AQUI, "api", "contexto.js")
s = open(p, encoding="utf-8").read()
i, j = s.index(INI), s.index(FIN) + len(FIN)
open(p, "w", encoding="utf-8").write(s[:i] + "\n".join(bloque) + s[j:])
print("reglas copiadas a", p)
