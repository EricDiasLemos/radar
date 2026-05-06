"""Teste rápido de conectividade e parsing de cada fonte."""
import sys
sys.path.insert(0, "/app/scripts")

from scraper import scrape_linkedin, scrape_vagas_com, scrape_programathor

QUERY = "DevOps"
LOCATION = "Belo Horizonte"
RESULTS = {}

def test(name, fn, *args):
    print(f"\n{'='*50}")
    print(f"  Testando: {name}")
    print(f"{'='*50}")
    try:
        jobs = fn(*args)
        RESULTS[name] = len(jobs)
        if jobs:
            j = jobs[0]
            print(f"  OK  {len(jobs)} vagas encontradas")
            print(f"  Primeira: {j.title[:60]}")
            print(f"  Empresa:  {j.company[:40]}")
            print(f"  Local:    {j.location[:40]}")
            print(f"  URL:      {j.url[:80]}")
            print(f"  Desc:     {j.description[:100]}..." if j.description else "  Desc:     (vazia)")
        else:
            print(f"  AVISO  0 vagas — site acessivel mas sem resultados")
            RESULTS[name] = 0
    except Exception as e:
        print(f"  ERRO: {e}")
        RESULTS[name] = -1

test("LinkedIn",     scrape_linkedin,     QUERY, LOCATION)
test("Vagas.com",    scrape_vagas_com,    QUERY)
test("Programathor", scrape_programathor, QUERY)

print(f"\n{'='*50}")
print("  RESUMO")
print(f"{'='*50}")
for name, count in RESULTS.items():
    status = "OK " if count > 0 else ("AVISO" if count == 0 else "ERRO ")
    label  = f"{count} vagas" if count >= 0 else "FALHOU"
    print(f"  {status}  {name:<15} {label}")
print()
