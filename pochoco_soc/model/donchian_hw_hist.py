"""
Modelo ciclo a ciclo de rtl/pochoco_donchian.v (BRAM con lectura síncrona).
Lo usa espino_iss.py para simular la unidad (DON_UNIT = 1) y sirvió para
verificar la lógica de la FSM antes de escribir el testbench en Verilog.
"""
# Modelo ciclo a ciclo de rtl/pochoco_donchian.v (BRAM con lectura síncrona)
LE,LX=500,250
class Unit:
    def __init__(s):
        s.ring=[0]*512; s.cmax=[0]*256; s.cmin=[0]*256
        s.ring_rd=0; s.cmax_rd=0; s.cmin_rd=0
        s.state='IDLE'; s.p=0; s.olx=0; s.ole=0; s.h=0; s.l=255; s.idx=0; s.n=0
        s.smax=0; s.smin=0; s.pmax=0; s.pmin=0
    def busy(s): return s.state!='IDLE'
    def clock(s, push=None):
        st=s.state; m8=lambda x:x&255; m9=lambda x:x&511
        rem_lx = s.n>=LX; rem_le = s.n>=LE
        cmax_dec=(s.cmax_rd-1)&0xFFFF; cmin_dec=(s.cmin_rd-1)&0xFF
        need_smax = rem_le and cmax_dec==0 and s.ole==s.h
        need_smin = rem_lx and cmin_dec==0 and s.olx==s.l
        # comb ports
        ring_ra=s.idx; ring_we=False; ring_wa=s.idx; ring_wd=s.p
        cmax_ra=s.p; cmax_we=False; cmax_wa=s.p; cmax_wd=0
        cmin_ra=s.p; cmin_we=False; cmin_wa=s.p; cmin_wd=0
        if st=='R1': ring_ra=m9(s.idx+262); cmax_ra=s.p; cmin_ra=s.p
        elif st=='R2':
            ring_ra=m9(s.idx+12); cmax_we=True; cmax_wa=s.p; cmax_wd=(s.cmax_rd+1)&0xFFFF
            cmin_we=True; cmin_wa=s.p; cmin_wd=(s.cmin_rd+1)&0xFF
        elif st=='R3':
            ring_we=True; ring_wa=s.idx; ring_wd=s.p; cmax_ra=s.ring_rd; cmin_ra=s.olx
        elif st=='R4':
            cmax_we=rem_le; cmax_wa=s.ole; cmax_wd=cmax_dec
            cmin_we=rem_lx; cmin_wa=s.olx; cmin_wd=cmin_dec
            cmax_ra=m8(s.h-1); cmin_ra=m8(s.l+1)
        elif st=='SCAN': cmax_ra=m8(s.pmax-1); cmin_ra=m8(s.pmin+1)
        # memorias: lectura con valor viejo (antes de la escritura del mismo flanco)
        n_ring_rd=s.ring[ring_ra]; n_cmax_rd=s.cmax[cmax_ra]; n_cmin_rd=s.cmin[cmin_ra]
        if ring_we: s.ring[ring_wa]=ring_wd
        if cmax_we: s.cmax[cmax_wa]=cmax_wd
        if cmin_we: s.cmin[cmin_wa]=cmin_wd
        # FSM (usa valores actuales de rdata)
        ns=dict()
        if st=='IDLE':
            if push is not None: ns['p']=push; ns['state']='R1'
        elif st=='R1': ns['state']='R2'
        elif st=='R2':
            ns['olx']=s.ring_rd
            if s.p>s.h: ns['h']=s.p
            if s.p<s.l: ns['l']=s.p
            ns['state']='R3'
        elif st=='R3': ns['ole']=s.ring_rd; ns['state']='R4'
        elif st=='R4':
            ns['idx']=m9(s.idx+1)
            if not rem_le: ns['n']=s.n+1
            ns['smax']=need_smax; ns['smin']=need_smin
            ns['pmax']=m8(s.h-1); ns['pmin']=m8(s.l+1)
            ns['state']='SCAN' if (need_smax or need_smin) else 'IDLE'
        elif st=='SCAN':
            if s.smax:
                if s.cmax_rd!=0: ns['h']=s.pmax; ns['smax']=0
                else: ns['pmax']=m8(s.pmax-1)
            if s.smin:
                if s.cmin_rd!=0: ns['l']=s.pmin; ns['smin']=0
                else: ns['pmin']=m8(s.pmin+1)
            if ((not s.smax) or s.cmax_rd!=0) and ((not s.smin) or s.cmin_rd!=0): ns['state']='IDLE'
        s.ring_rd,s.cmax_rd,s.cmin_rd=n_ring_rd,n_cmax_rd,n_cmin_rd
        for k,v in ns.items(): setattr(s,k,v)

