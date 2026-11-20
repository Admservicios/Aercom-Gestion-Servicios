const botonMenu = document.querySelector(".boton-menu-oficina");
const menuOficina = document.getElementById("menu-oficina");
const pantallaAngosta = window.matchMedia("(max-width: 56rem)");
const enlaceActivo = menuOficina.querySelector("[aria-current]");

function mostrarMenu(abierto) {
    botonMenu.setAttribute("aria-expanded", String(abierto));
    menuOficina.hidden = pantallaAngosta.matches && !abierto;
    if (!pantallaAngosta.matches && enlaceActivo) {
        const oculto = enlaceActivo.getBoundingClientRect().bottom - menuOficina.getBoundingClientRect().bottom;
        if (oculto > 0) menuOficina.scrollTop += oculto + 12;
    }
}

botonMenu.hidden = false;
mostrarMenu(false);
pantallaAngosta.addEventListener("change", () => mostrarMenu(false));
botonMenu.addEventListener("click", () => {
    const abrir = botonMenu.getAttribute("aria-expanded") === "false";
    mostrarMenu(abrir);
    if (abrir) {
        const enlace = enlaceActivo || menuOficina.querySelector(".enlace-inicio");
        enlace.focus();
    }
});
document.addEventListener("keydown", (evento) => {
    if (evento.key === "Escape" && botonMenu.getAttribute("aria-expanded") === "true") {
        mostrarMenu(false);
        botonMenu.focus();
    }
});
