    // === Configuración ===
    const RASA_REST_URL = "http://localhost:5005/webhooks/rest/webhook"; // sericio rest
    const SENDER_ID = "web_user_" + Math.random().toString(36).slice(2,9);

    // === UI helpers ===
    const chat = document.getElementById("chatBox");
    const scrollArea = document.getElementById("chatScroll");
    const input = document.getElementById("msg");
    const sendBtn = document.getElementById("sendBtn");
    const fab = document.getElementById("fab");
    const statusBadge = document.getElementById("statusBadge");

    function nowTime(){
      const d = new Date();
      return d.toLocaleTimeString([], {hour:"2-digit", minute:"2-digit"});
    }
    function addMsg(text, from="bot"){
      const wrap = document.createElement("div");
      wrap.className = `msg ${from}`;
      const bubble = document.createElement("div");
      bubble.className = "bubble";
      bubble.textContent = text;
      const meta = document.createElement("div");
      meta.className = "meta";
      meta.textContent = (from==="bot"?"Bot":"Tú") + " • " + nowTime();

      bubble.appendChild(document.createElement("br"));
      wrap.appendChild(bubble);
      wrap.appendChild(meta);
      scrollArea.appendChild(wrap);
      scrollArea.scrollTop = scrollArea.scrollHeight;
    }
    function addTyping(){
      const wrap = document.createElement("div");
      wrap.className = "typing";
      wrap.id = "typingRow";
      wrap.innerHTML = `<span class="dot"></span><span class="dot"></span><span class="dot"></span>`;
      scrollArea.appendChild(wrap);
      scrollArea.scrollTop = scrollArea.scrollHeight;
    }
    function removeTyping(){
      const t = document.getElementById("typingRow");
      if(t) t.remove();
    }

    // === Envío al bot ===
    async function sendToRasa(message){
      // pinta mi mensaje
      addMsg(message, "user");

      // typing
      addTyping();
      try{
        const res = await fetch(RASA_REST_URL, {
          method:"POST",
          headers:{ "Content-Type":"application/json" },
          body: JSON.stringify({ sender: SENDER_ID, message })
        });

        const data = await res.json().catch(()=>[]);
        removeTyping();

        if(!Array.isArray(data) || data.length===0){
          addMsg("No recibí respuesta del asistente. Intenta de nuevo.", "bot");
          return;
        }
        // Rasa REST puede devolver {text}, {image}, {buttons}, etc.
        data.forEach(m => {
          if(m.text) addMsg(m.text, "bot");
          if(m.image) addMsg("🖼️ [Imagen]: " + m.image, "bot");
          if(m.buttons && Array.isArray(m.buttons) && m.buttons.length){
          addButtons(m.buttons);}

        });
      }catch(err){
        removeTyping();
        console.error(err);
        statusBadge.textContent = "Error conexión";
        statusBadge.classList.add("err");
        addMsg("⚠️ No puedo conectar con el servidor. Verifica que Rasa esté activo.", "bot");
      }
    }

    // === Eventos UI ===
    sendBtn.addEventListener("click", () => {
      const txt = (input.value || "").trim();
      if(!txt) return;
      input.value = "";
      sendToRasa(txt);
    });
    input.addEventListener("keydown", (e) => {
      if(e.key === "Enter"){
        e.preventDefault();
        sendBtn.click();
      }
    });
    fab.addEventListener("click", ()=>{
      // alterna mostrar/ocultar chat (para móvil)
      chat.classList.toggle("hide");
      if(!chat.classList.contains("hide")){
        input.focus();
      }
    });

    // === Arranque ===
    (async function boot(){
      // Mostrar chat por defecto en escritorio, ocultarlo en pantallas muy pequeñas si quieres:
      if(window.innerWidth < 420){
        // chat.classList.add("hide"); // (opcional) iniciar oculto en móviles
      }
      // Mensaje de bienvenida local + disparo de saludo al bot
      addMsg("👋 ¡Hola! Soy tu asistente de Farmacias Emanuel. Escribe 'hola' para iniciar o 'ayuda' para conocer nuestras opciones disponibles", "bot");

      // Auto-saludo al bot para que muestre el menú
      setTimeout(()=>sendToRasa("hola"), 500);

      // Ping rápido para mostrar estado
      try{
        const res = await fetch(RASA_REST_URL, {
          method:"POST",
          headers:{ "Content-Type":"application/json" },
          body: JSON.stringify({ sender: SENDER_ID, message: "/deny_ping_ignore" })
        });
        if(res.ok){
          statusBadge.textContent = "Conectado";
          statusBadge.classList.remove("err");
        }else{
          statusBadge.textContent = "Conectado (REST)";
        }
      }catch{
        statusBadge.textContent = "Sin conexión";
        statusBadge.classList.add("err");
      }
    })();

    //funcionalidades botones rasa
    function addButtons(buttons){
  // buttons: [{title, payload}, ...]
  const group = document.createElement("div");
  group.className = "btn-group";
  buttons.forEach(b=>{
    const btn = document.createElement("button");
    btn.className = "choice";
    btn.type = "button";
    btn.textContent = b.title || b.payload || "Opción";
    btn.addEventListener("click", ()=>{
      // Deshabilitar el grupo después del click para evitar dobles envíos
      [...group.querySelectorAll("button")].forEach(x=>x.disabled = true);

      // Si el payload viene como intent (/otro_medicamento), úsalo tal cual.
      // Si no, manda el payload si existe; de lo contrario, el title.
      const payload = (b.payload && b.payload.trim()) || (b.title || "").trim();

      // Pinta mi mensaje local y envía al bot
      input.value = payload;
      sendBtn.click();
    });
    group.appendChild(btn);
  });
  scrollArea.appendChild(group);
  scrollArea.scrollTop = scrollArea.scrollHeight;
  }