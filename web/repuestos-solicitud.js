const repuestos = document.getElementById("repuestos");
const repuestoVacio = document.getElementById("repuesto-vacio");
const total = document.getElementById("id_repuestos-TOTAL_FORMS");
const maximo = document.getElementById("id_repuestos-MAX_NUM_FORMS");
const agregar = document.getElementById("agregar-repuesto");

function actualizarBoton() {
    agregar.disabled = Number(total.value) >= Number(maximo.value);
}

agregar.addEventListener("click", () => {
    const indice = Number(total.value);
    if (indice >= Number(maximo.value)) return;
    const renglon = repuestoVacio.content.cloneNode(true);
    renglon.querySelectorAll("[id], [name], [for]").forEach((elemento) => {
        for (const atributo of ["id", "name", "for"]) {
            const valor = elemento.getAttribute(atributo);
            if (valor) elemento.setAttribute(atributo, valor.replaceAll("__prefix__", String(indice)));
        }
    });
    renglon.querySelector("legend").textContent = `Repuesto ${indice + 1}`;
    repuestos.append(renglon);
    total.value = indice + 1;
    actualizarBoton();
});
actualizarBoton();
