// Normalización sobre el área real de imagen, incluyendo bandas de object-fit:contain.
export function imagePoint(clientX: number, clientY: number,
  rect: {left:number;top:number;width:number;height:number}, imageWidth:number, imageHeight:number): [number,number] | null {
  if (!imageWidth || !imageHeight || !rect.width || !rect.height) return null;
  const scale=Math.min(rect.width/imageWidth,rect.height/imageHeight);
  const width=imageWidth*scale, height=imageHeight*scale;
  const x=(clientX-rect.left-(rect.width-width)/2)/width;
  const y=(clientY-rect.top-(rect.height-height)/2)/height;
  return x<0 || x>1 || y<0 || y>1 ? null : [x,y];
}
