import {fireEvent,render,screen,waitFor} from "@testing-library/react";
import {afterEach,beforeEach,expect,it,vi} from "vitest";
import TelegramSetup from "../src/components/TelegramSetup";

beforeEach(()=>vi.stubGlobal("fetch",vi.fn()));
afterEach(()=>vi.unstubAllGlobals());

it("valida el bot, limpia el campo protegido y no almacena el token en el navegador",async()=>{
  const changed=vi.fn().mockResolvedValue(undefined);
  vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({enabled:true,bot_username:"VisionBot"})));
  render(<TelegramSetup token="admin-test" enabled={false} onChange={changed}/>);
  const input=screen.getByLabelText("Token de BotFather");
  expect(input).toHaveAttribute("type","password");
  expect(screen.getByRole("button",{name:"Conectar bot"})).toBeDisabled();
  fireEvent.change(input,{target:{value:"123456:secret-token-test"}});
  fireEvent.click(screen.getByRole("button",{name:"Conectar bot"}));
  await screen.findByText("Bot conectado. Ya puedes vincular al familiar.");
  expect(fetch).toHaveBeenCalledWith("/api/telegram",expect.objectContaining({method:"POST",body:JSON.stringify({token:"123456:secret-token-test"})}));
  expect(input).toHaveValue("");
  expect(changed).toHaveBeenCalledOnce();
  expect(localStorage.length).toBe(0);
  expect(sessionStorage.length).toBe(0);
});

it("muestra el error sin declarar conectado un token rechazado",async()=>{
  const changed=vi.fn();
  vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({detail:"Revisa el token que te dio BotFather."}),{status:400}));
  render(<TelegramSetup token="admin-test" enabled={false} onChange={changed}/>);
  fireEvent.change(screen.getByLabelText("Token de BotFather"),{target:{value:"bad-token"}});
  fireEvent.click(screen.getByRole("button",{name:"Conectar bot"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("Revisa el token");
  expect(changed).not.toHaveBeenCalled();
  expect(screen.queryByText("Bot conectado. Ya puedes vincular al familiar.")).not.toBeInTheDocument();
});

it("desconecta solo por acción explícita",async()=>{
  const changed=vi.fn().mockResolvedValue(undefined);
  vi.mocked(fetch).mockResolvedValue(new Response("{}"));
  render(<TelegramSetup token="admin-test" enabled username="VisionBot" onChange={changed}/>);
  expect(fetch).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button",{name:"Desconectar bot"}));
  await waitFor(()=>expect(changed).toHaveBeenCalledOnce());
  expect(fetch).toHaveBeenCalledWith("/api/telegram",expect.objectContaining({method:"DELETE"}));
});
