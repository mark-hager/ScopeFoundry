
import pyqtgraph as pg
from pyqtgraph.Qt import QtGui, QtCore
import numpy as np
import math
import threading

# TODO 
#  connect color scales together DONE (If connected to a HistLut)
#  always show lowest zoom behind DONE
# show one lower zoom underneath


class TileItem(object):
    
    def __init__(self, zmi, zoom, ii, jj):
        self.zmi = zmi
        self.image_item = None
        self.zoom_tile_coord = zoom, ii, jj
        
        # zoom
        # zoom z=0 --> original size: tile slice (ii*tile_size : (ii+1)*tile_size : 1)
        # zoom z=1 --> half size: tile slice (ii*tile_size*2 : (ii+1)*tile_size*2 : 2)
        # zoom z=N ---> tile slice (ii*tile_size*(2**z) : (ii+1)*tile_size*(2**z) : (2**z) )
        z = zoom
        zf = 2**z
        Nt = self.zmi.tile_size
        tile_shape = list(self.zmi.image.shape)
        tile_shape[0] = Nt
        tile_shape[1] = Nt
        self.data = np.zeros(tuple(tile_shape), dtype=self.zmi.image.dtype)
        if self.zmi.fill is not None:
            self.data += self.zmi.fill
        
        print("---", ii, jj, Nt, zoom, zf)
        im = zmi.image[ii*Nt*zf:(ii+1)*Nt*zf:zf,
                       jj*Nt*zf:(jj+1)*Nt*zf:zf]
        self.data[:im.shape[0], :im.shape[1]] = im 
        
        # make border pixels
        #self.data[0:5,:] = 0
        #self.data[:,0:5] = 0
                
        #print("tile", self.zoom_tile_coord, self.data.shape)
        
        # Old way to compute tile rectangle based on zmi rectangle
        """
        x0, y0, w, h = self.zmi.rect        
        orig_pixel_size_x = w / zmi.image.shape[0]
        orig_pixel_size_y = h / zmi.image.shape[1]

        x = x0 +ii*Nt*zf*orig_pixel_size_x
        y = y0 +jj*Nt*zf*orig_pixel_size_y
        
        self.rect = (x,y, Nt*zf*orig_pixel_size_x, Nt*zf*orig_pixel_size_y)
        """
        self.transform = QtGui.QTransform()
        
        self.rebuild_data = False
        self.visible = False
    
    # def create_image_item(self):
    #
        # if not self.image_item is None:
            # self.zmi.plot.removeItem(self.image_item)
            # del self.image_item
        # self.image_item = pg.ImageItem(self.data, autoLevels=False)
        # self.image_item.setRect(pg.QtCore.QRectF(*self.rect))
        #
        # self.zmi.plot.addItem(self.image_item)
        
    def set_visible(self, vis=True, force_replacement=False):
        
        #print("set_visible", self.zoom_tile_coord, vis)

        if (not vis) or (not self.image_item is None) or force_replacement:
            self.zmi.plot.removeItem(self.image_item)
            self.image_item = None
            self.visible = False
        
        if vis and (self.image_item is None):
            self.image_item = pg.ImageItem(self.data, **self.zmi.im_kwargs)
            #self.image_item.setRect(pg.QtCore.QRectF(*self.rect))
            self.image_item.setTransform(self.recomputeTransform())
            self.image_item.setZValue(self.zmi.z_value-self.zoom_tile_coord[0])
            self.zmi.plot.addItem(self.image_item)
            self.visible = True
            
    def recomputeTransform(self):
        zoom, ii, jj = self.zoom_tile_coord
        zf = 2**zoom
        
        Nx, Ny = self.zmi.image.shape[0:2]
        
        Nt = self.zmi.tile_size 
        
        x = ii*zf* Nt
        y = jj*zf* Nt
    
        tr = self.tile_transform = QtGui.QTransform()
        
        sx = zf#*Nt/Nx * Nt
        sy = zf#*Nt/Ny * Nt
        tr.translate(x, y)
        tr.scale(sx, sy)
        
        #print(f"Nt={Nt}, z={z}, zf={zf}, ii={ii}, jj={jj}, x={x}, y={y}, scale {sx} {sy}")
    
        # full transform 
        self.full_transform = self.tile_transform * self.zmi.transform
        return self.full_transform

        
    
class ZoomableMapItems(QtCore.QObject):
    
    sigImageChanged = QtCore.Signal()

    
    def __init__(self, plot_item, image=None, rect=None, transform=None, 
                 tile_size=256, z_value=100, fill=None,
                 **kwargs):
        
        QtCore.QObject.__init__(self)
        
        """
        if rect=None, go by pixels
        otherwise rect=(x0,y0,w,h)
        
        kwargs are sent to setImage of imageItems
        """
        
        self.tile_size = tile_size
        self.z_value = z_value
        self.fill = fill
        self.im_kwargs = kwargs

        self.plot = plot_item
        self.vb  = self.plot.getViewBox()
        
        self.tile_cache = dict()
        self.visible_tiles = dict()
        
        self.lut = kwargs.get('lut', None)
        
        
        #self.plot.sigRangeChanged.connect(self.on_range_changed)
        
        self.sigprox = pg.SignalProxy(
                            signal=self.plot.sigRangeChanged,
                            #delay=0.1,
                            rateLimit=30,
                            slot=self.on_range_changed)

        
        self.image = image
        
        if transform is None:
            self.transform = QtGui.QTransform()
            if not (rect is None):
                self.setRect(rect)
        else: 
            self.transform = transform
#            rect = (0,0, image.shape[0], image.shape[1])
#        self.rect = tuple(rect)
        
        #self.base_imageitem = pg.ImageItem(self.image)
        #self.base_imageitem.setRect(pg.QtCore.QRectF(*rect))

        #self.plot.addItem(self.base_imageitem)
        self.lock = threading.Lock()
        
        #self.on_range_changed(None, new_range=( (rect[0], rect[0]+rect[2]), (rect[1], rect[1]+rect[3])))
        #zf_max  = np.max(self.image.shape[0:1])/self.tile_size
        #z_max = int(math.ceil(math.log2(zf_max)))
        #print(f"zf_max: {zf_max}, z_max {z_max}: {self.tiles_at_zoom(z_max)}")
        z_max = self.get_max_zoom() # FIXME
        print('z_max', z_max)
        self.get_tile(z_max, 0,0).set_visible()

    def clear_tile_cache(self, clear_visible=False):
        pass
        #TODO
                   
    def get_tile(self, z, ii,jj):
        if (z, ii,jj) not in self.tile_cache:
            self.tile_cache[(z,ii,jj)] = TileItem(self, z, ii, jj)
        return self.tile_cache[(z,ii,jj)]

        
    def tiles_at_zoom(self, z):
        zfi = 2**z
        Nt = self.tile_size
        Nx_tiles = int(np.ceil(self.image.shape[0]/zfi/Nt))
        Ny_tiles = int(np.ceil(self.image.shape[1]/zfi/Nt))
        return (Nx_tiles, Ny_tiles)
    

    def get_max_zoom(self):
        
        # FIXME!
        
        # Find the zoom where Nx_tiles or Ny_tiles goes to 1
        # Nx_tiles = (im.shape[0]/zfi/Nt)
        zf_max = np.max(self.image.shape[0:1])/self.tile_size 
        z_max = int(math.ceil(math.log2(zf_max)))
        
        z_max = max(0, z_max)
        """
        # compute zoom level
        Nt = self.tile_size
        x0, y0, w, h = self.rect
        
        orig_pixel_size_x = w / self.image.shape[0]
        orig_pixel_size_y = h / self.image.shape[1]
        
        #print("Pixel Size", self.vb.viewPixelSize(), orig_pixel_size_x)
        zf = self.vb.viewPixelSize()[0]/orig_pixel_size_x
        zf_max  = np.min(self.image.shape[0:1])/self.tile_size
        z_max = int(math.ceil(math.log2(zf_max)))
        """
        return z_max
    
    def on_range_changed(self, src, new_range=None):
        if new_range is None:
            new_range = self.vb.viewRange()
        
        # OLD METHOD BASED ON Rectangles (not transforms)
        """
        # compute zoom level
        Nt = self.tile_size
        x0, y0, w, h = self.rect
        
        orig_pixel_size_x = w / self.image.shape[0]
        orig_pixel_size_y = h / self.image.shape[1]
        
        #print("Pixel Size", self.vb.viewPixelSize(), orig_pixel_size_x)
        zf = self.vb.viewPixelSize()[0]/orig_pixel_size_x
        zf_max  = np.min(self.image.shape[0:1])/self.tile_size
        z_max = int(math.ceil(math.log2(zf_max)))
        z = min(max(int(np.floor(np.log2(zf))),0), z_max)
        zfi = 2**z
        
        #print(f"zf={zf} z={z}, zfi={zfi}, zf_max={zf_max}, z_max={z_max}")
        
        
        Nx_tiles = int(np.ceil(self.image.shape[0]/zfi/Nt))
        Ny_tiles = int(np.ceil(self.image.shape[1]/zfi/Nt))
        
        #print("N data pixels per view pixel", self.vb.viewPixelSize()[0]/orig_pixel_size_x  )
        #print("N view pixels per data pixel", orig_pixel_size_x / self.vb.viewPixelSize()[0])

        # Update Tile Cache
        
        # which tiles should be visible?
        #know z from above
        
        
        
        (xl,xr), (yb, yt) = new_range
        
        

        
        # tile corner formula
        #x = x0 +ii*Nt*zf*orig_pixel_size_x
        #y = y0 +jj*Nt*zf*orig_pixel_size_y
        
        # flipping this
        ii0 = (xl - x0) / (Nt*zfi*orig_pixel_size_x)
        ii0 = max(0, math.floor(ii0)) # clip at zero
        ii1 = (xr - x0) / (Nt*zfi*orig_pixel_size_x)
        ii1 = min(math.ceil(ii1), Nx_tiles)
        
        jj0 = (yb - y0) / (Nt*zfi*orig_pixel_size_y)
        jj0 = max(0, math.floor(jj0))
        jj1 = (yt - y0) / (Nt*zfi*orig_pixel_size_y)
        jj1 = min(math.ceil(jj1), Ny_tiles)
        """
        
        tr = self.transform
        tI,invertible = tr.inverted()
        

        # Use the vector of the bottom-left to top-right of view as a measuring stick
        # in all coordinate systems to determine zoom factor and visibility of tiles
        
        (xl,xr), (yb, yt) = new_range  # coordinates in View Space
        
        # pixel size in view coordinate system
        px, py = self.vb.viewPixelSize()
        
        # Coordinates in Image original pixel space
        x0, y0 = tI.map(xl,yb)
        x1, y1 = tI.map(xr,yt)
        
        
        #
        bl_tr_dist_view = np.sqrt( (xr-xl)**2 + (yt-yb)**2)
        bl_tr_dist_view_px = np.sqrt( ((xr-xl)/px)**2 + ((yt-yb)/py)**2)
        bl_tr_dist_orig = np.sqrt( (x1-x0)**2 + (y1-y0)**2)
        
        print("bl_tr_dist_view", bl_tr_dist_view)
        print("bl_tr_dist_view_px", bl_tr_dist_view_px)
        print("bl_tr_dist_orig", bl_tr_dist_orig)

        zf = bl_tr_dist_orig/bl_tr_dist_view_px
        

        z_max = self.get_max_zoom()
        print("zoom factor", zf, 'z_max', z_max)
        
        zoom = min(max(int(np.floor(np.log2(zf))),0), z_max)
        zfi = 2**zoom # integer power of two zoom factor    

        # Num of tiles possible at current zoom
        Nx_tiles, Ny_tiles = self.tiles_at_zoom(zoom)
        Nt = self.tile_size        
        
        print("zoom", zoom,'zfi', zfi, "Tiles at zoom", Nx_tiles, Ny_tiles )

        # Tile limits ii0 to ii1, jj0 to jj1
        ii0 = x0 / (zfi*Nt)
        ii0 = max(0, math.floor(ii0)) # clip at zero
        ii1 = x1 / (zfi*Nt)
        ii1 = min(math.ceil(ii1), Nx_tiles)
    
        jj0 = y0 / (zfi*Nt)
        jj0 = max(0, math.floor(jj0)) # clip at zero
        jj1 = y1 / (zfi*Nt)
        jj1 = min(math.ceil(jj1), Ny_tiles)    

                
        print(f"allowed tiles zoom level {zoom}, x: {ii0} to {ii1}, y: {jj0} to {jj1}")
        
        if self.lock.locked():
            return
        with self.lock:
            # find tiles in visible_tiles that are not allowed and set_visible False
            for (zt, iit, jjt) in list(self.visible_tiles.keys()):
                tile = self.visible_tiles[(zt, iit, jjt)]
                vis = True
                if zt != zoom: # Wrong zoom
                    vis = False
                else:
                    if not ii0 <= iit < ii1: # out of range x
                        vis = False
                    if not jj0 <= jjt < jj1: # out of range y
                        vis = False            
                if not vis:
                    tile.set_visible(False)
                    del self.visible_tiles[(zt, iit, jjt)]
            
            # find or create allowed Tiles in tile cache
            for ii in range(ii0,ii1):
                for jj in range(jj0,jj1):
                    t = self.get_tile(zoom, ii, jj)
                    # set tiles to visible (add image item)
                    t.set_visible(True)
                    # add tiles to visible_tiles dictionary
                    self.visible_tiles[(zoom,ii,jj)] = t
        
        Nx, Ny = self.tiles_at_zoom(z_max)
        for ii in range(Nx):
            for jj in range(Ny):
                self.get_tile(z_max, ii,jj).set_visible(True)
        
        N_visible = len(self.visible_tiles)
        #self.plot.setTitle(
        print(f"zf={zf} z={zoom}, zfi={zfi}. Tiles {Nx_tiles} x {Ny_tiles}, {N_visible} tiles shown")

    def getHistogram(self, bins='auto', step='auto', perChannel=False, targetImageSize=200,
                     targetHistogramSize=500, **kwds):
        z_max = self.get_max_zoom()
        # Nx, Ny = self.tiles_at_zoom(z_max)
        # for ii in range(Nx):
            # for jj in range(Ny):
                # tile = self.get_tile(z_max, ii,jj)
                # return tile.image_item.getHistogram()
        return self.get_tile(z_max,0,0).image_item.getHistogram()
            
    def setLookupTable(self, lut, update=True):
        if lut is not self.lut:
            self.lut = lut
            self.im_kwargs['lut'] = lut
        for (zt, iit, jjt) in list(self.visible_tiles.keys()):
            tile = self.visible_tiles[(zt, iit, jjt)]
            tile.image_item.setLookupTable(lut,update)

    def setLevels(self, levels, update=True):
        # if not 
        self.im_kwargs['levels'] = levels
        for (zt, iit, jjt) in list(self.visible_tiles.keys()):
            tile = self.visible_tiles[(zt, iit, jjt)]
            tile.image_item.setLevels(levels,update)
            
    def setRect(self, rect):
        """Scale and translate the image to fit within rect (must be a QRect or QRectF) or iterable [left top width hight]."""
        if not isinstance(rect, QtCore.QRect) or  isinstance(rect, QtCore.QRect):
            rect = QtCore.QRectF(*rect)
        tr = QtGui.QTransform()
        tr.translate(rect.left(), rect.top())
        tr.scale(rect.width() / self.image.shape[0], rect.height() / self.image.shape[1])
        self.setTransform(tr)

    def setTransform(self, tr):
        self.transform = tr
        for (zt, iit, jjt) in list(self.visible_tiles.keys()):
            tile = self.visible_tiles[(zt, iit, jjt)]
            tile.recomputeTransform()

        
        

