# Equipos: de quién es cada PC

Un fichero por persona, `nombre-apellido.json`, con los PC que son suyos. Al
empezar cada sesión, el hook `documentar.mjs` lee el nombre del equipo
(`COMPUTERNAME`) y lo busca aquí. **Manda el nombre del equipo.**

- Si el PC es de una persona, Claude trabaja con ella sin preguntar, y si el
  chat dice ser otra, no lo acepta sin más: avisa y pide que se aclare.
- Si el PC no está, Claude pregunta «¿quién eres?» y, dicho, añade el PC al
  fichero de esa persona.

Solo escribe cada fichero su dueño (o el agente que trabaja con esa persona), para
que OneDrive no cree conflictos.

Es un testigo para no confundir a una persona con otra, no una medida de
seguridad.

```json
{
  "persona": "Nombre Apellido",
  "pcs": ["NOMBRE-DEL-EQUIPO"],
  "cuentas": ["correo@example.com"],
  "actualizado": "AAAA-MM-DD · Nombre Apellido (con Claude)"
}
```
