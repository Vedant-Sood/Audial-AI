"""Binary light raster of the restored 49-landmark ISL pose convention."""
import numpy as np

HAND_EDGES = [(0,1),(1,2),(2,3),(3,4),(0,5),(5,6),(6,7),(7,8),(5,9),(9,10),(10,11),(11,12),(9,13),(13,14),(14,15),(15,16),(13,17),(0,17),(17,18),(18,19),(19,20)]
EDGES = [(1,2),(1,3),(3,5),(2,4),(4,6)] + [(a+offset,b+offset) for offset in [7,28] for a,b in HAND_EDGES]


def rasterize(points, columns=128, rows=96):
    points = np.asarray(points, np.float32)
    if points.shape != (49,4) or not np.isfinite(points).all():
        raise ValueError("Light display needs finite [49,4] camera-coordinate poses.")
    grid = np.zeros((rows, columns), bool)
    visible = (points[:,3] > .3) & (points[:,0] >= 0) & (points[:,0] <= 1) & (points[:,1] >= 0) & (points[:,1] <= 1)
    coordinates = np.rint(points[:,:2] * [columns-1,rows-1]).astype(int)
    for index in np.flatnonzero(visible):
        x,y = coordinates[index]; grid[y,x] = True
    for a,b in EDGES:
        if not visible[a] or not visible[b]:
            continue
        x,y = coordinates[a]; tx,ty = coordinates[b]
        dx,dy = abs(tx-x), -abs(ty-y); sx,sy = 1 if x<tx else -1, 1 if y<ty else -1
        error = dx+dy
        while True:
            grid[y,x] = True
            if x==tx and y==ty: break
            doubled = 2*error
            if doubled>=dy: error+=dy; x+=sx
            if doubled<=dx: error+=dx; y+=sy
    return grid
