# Atajos de teclado — CopyPasteRemote

Referencia rápida de los atajos del cliente.

> En un *pool*, cada máquina tiene un número de **buzón** (slot 1, 2, 3…). Envías a un
> buzón y la máquina dueña de ese buzón lo recibe.

## Atajos por defecto

| Acción | Atajo |
|--------|-------|
| **Enviar** el portapapeles al buzón **N** | **`Ctrl + Shift + F<N>`** |
| **Recibir / pegar** lo del buzón **N** | **`Ctrl + Shift + <N>`** |
| Pegar lo de **mi propio** buzón | **`Ctrl + Shift + 0`** |

Mnemotécnica: **F = enviar** (Forward), **número solo = recibir**. F1–F9 cubren los
buzones 1–9.

## Flujo

1. **Copia** con `Ctrl+C` (texto, archivos o carpetas desde el Explorador).
2. **Envía** al buzón destino: `Ctrl+Shift+F<N>`.
3. En la **máquina destino**, recibe/pega: `Ctrl+Shift+<N>` (con `auto_paste` activo,
   se pega solo con `Ctrl+V` al recibir).

## Ejemplo (máquina 1 ↔ máquina 2)

- **1 → 2:** en la máquina 1, `Ctrl+C` y `Ctrl+Shift+F2`; en la máquina 2, `Ctrl+Shift+2`.
- **2 → 1:** en la máquina 2, `Ctrl+C` y `Ctrl+Shift+F1`; en la máquina 1, `Ctrl+Shift+1`.
- **Archivos:** igual que el texto (selección en el Explorador → `Ctrl+C` → enviar; en el
  destino pega en una carpeta).

## Notas

- **Copia tú primero** con `Ctrl+C`: el auto-copiado (`copy_before_send`) está
  **desactivado por defecto** para no alterar/cortar la selección.
- **Por qué no `Ctrl+Alt+N`:** en teclados con **AltGr** (p. ej. español), `Ctrl+Alt`
  equivale a `AltGr`, así que `Ctrl+Alt+1` escribe `|`, `Ctrl+Alt+2` `@`, etc. Por eso el
  envío usa **teclas de función**, que no generan carácter.
- **Personalizar:** edita `push_hotkeys` / `pull_hotkeys` / `pull_own_hotkey` en
  `%APPDATA%\CopyPasteRemote\config.json` (sintaxis de la librería `keyboard`, p. ej.
  `ctrl+shift+f1`). Evita `Ctrl+Alt+dígito` y `Win+dígito`.
