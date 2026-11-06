import {describe,it,expect} from "vitest";
import {imagePoint} from "../src/geometry";
import {monitorTitle} from "../src/monitorStatus";

describe("coordenadas sobre imagen",()=>{
  it("excluye las bandas y mantiene las proporciones al redimensionar",()=>{
    const square={left:10,top:20,width:400,height:400};
    expect(imagePoint(210,220,square,1600,900)).toEqual([.5,.5]);
    expect(imagePoint(210,30,square,1600,900)).toBeNull();
    expect(imagePoint(410,220,square,1600,900)).toEqual([1,.5]);
    expect(imagePoint(110,120,{left:10,top:20,width:200,height:200},1600,900)).toEqual([.5,.5]);
  });
  it("no calcula sobre elementos sin tamaño",()=>{
    expect(imagePoint(0,0,{left:0,top:0,width:0,height:0},960,540)).toBeNull();
  });
});

it("distingue la capacidad temporal insuficiente del estado normal",()=>{
  expect(monitorTitle(true,{type:"status",timestamp:1,level:"ok",camera:"streaming",reasons:["insufficient_history"],model_error:null})).toBe("Datos temporales insuficientes");
});

it("una pose no evaluable nunca se etiqueta como ausencia de caída",()=>{
  expect(monitorTitle(true,{type:"status",camera_id:"cam-1",timestamp:1,level:"ok",camera:"streaming",reasons:["no_pose"],model_error:null,diagnostics:null})).toBe("No evaluable: torso no visible");
});
