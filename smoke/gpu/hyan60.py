import sys,subprocess,numpy as np
w,h=1280,800
p=subprocess.run(["ffmpeg","-v","error","-i",sys.argv[1],"-f","rawvideo","-pix_fmt","rgb24","-"],capture_output=True).stdout
n=len(p)//(w*h*3); a=np.frombuffer(p,np.uint8)[:n*w*h*3].reshape(n,h,w,3)
col=a[:,:,140,:].astype(int)
cy=((col[:,:,2]>180)&(col[:,:,1]>150)&(col[:,:,0]<120)).sum(1)
prev=None; ch=[]
for i,c in enumerate(cy):
    if c!=prev: ch.append((i,c)); prev=c
grow=[(i,c) for i,c in ch if 24<c<=264]
print("frames",n,"distinct changes",len(ch))
dec=[(ch[k][0],ch[k-1][1],ch[k][1]) for k in range(1,len(ch)) if ch[k][1]<ch[k-1][1] and ch[k][1]>0]
print("decreases (frame,from,to):",dec[:10])
# growth span: first frame > 24 to first frame ==264
f0=next(i for i,c in enumerate(cy) if c>24); f1=next(i for i,c in enumerate(cy) if c>=264)
seg=cy[f0:f1+1]; steps=(np.diff(seg)!=0).sum()
print(f"open anim: {(f1-f0)/60:.2f}s, {steps} height steps over {f1-f0} frames (60 Hz capture); max gap {max(np.diff([i for i in range(f0,f1+1) if i==f0 or cy[i]!=cy[i-1]]))} frames")
