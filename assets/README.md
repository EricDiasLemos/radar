# Assets

Arquivos estáticos usados pelo Job Radar.

## curriculo.pdf

**Adicione seu currículo aqui como `curriculo.pdf`** — esse é o arquivo
anexado automaticamente em toda candidatura enviada pelo `mailer.py`.

### Como adicionar

```bash
# Copie seu PDF pra cá com o nome exato 'curriculo.pdf'
cp /caminho/do/seu/curriculo.pdf assets/curriculo.pdf

# Commit
git add assets/curriculo.pdf
git commit -m "chore: adiciona currículo"
git push
```

Quando o arquivo estiver presente, o log do scan vai mostrar:

```
Currículo anexado
```

Sem ele, aparece o warning:

```
⚠️  Currículo não encontrado em ... — email enviado SEM anexo!
```
