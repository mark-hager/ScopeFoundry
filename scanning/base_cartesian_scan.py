'''
Created on Feb 4, 2016

@author: Edward Barnard
'''

from ScopeFoundry import Measurement
from ScopeFoundry.helper_funcs import sibling_path, load_qt_ui_file
import numpy as np
import pyqtgraph as pg
import time
from ScopeFoundry import h5_io
from hardware_components import apd_counter
from PySide import QtCore
from ScopeFoundry import LQRange
import warnings

def ijk_zigzag_generator(dims, axis_order=(0,1,2)):
    """3D zig-zag scan pattern generator with arbitrary fast axis order"""

    ax0, ax1, ax2 = axis_order
    
    for i_ax0 in range( dims[ax0] ):
        zig_or_zag0 = (1,-1)[i_ax0 % 2]
        for i_ax1 in range( dims[ax1] )[::zig_or_zag0]:
            zig_or_zag1 = (1,-1)[(i_ax0+i_ax1) % 2]
            for i_ax2 in range( dims[ax2] )[::zig_or_zag1]:
            
                ijk = [0,0,0]
                ijk[ax0] = i_ax0
                ijk[ax1] = i_ax1
                ijk[ax2] = i_ax2
                
                yield tuple(ijk)
    return

class BaseCartesian2DSlowScan(Measurement):
    name = "base_cartesian_slowscan"
    
    def setup(self):
        self.ui_filename = sibling_path(__file__,"cart_scan_base.ui")
        self.ui = load_qt_ui_file(self.ui_filename)
        self.ui.show()
        self.ui.setWindowTitle(self.name)

        self.display_update_period = 0.001 #seconds

        #connect events        

        # local logged quantities
        lq_params = dict(dtype=float, vmin=0,vmax=100, ro=False, unit='um' )
        self.h0 = self.settings.New('h0',  initial=25, **lq_params  )
        self.h1 = self.settings.New('h1',  initial=45, **lq_params  )
        self.v0 = self.settings.New('v0',  initial=25, **lq_params  )
        self.v1 = self.settings.New('v1',  initial=45, **lq_params  )

        lq_params = dict(dtype=float, vmin=1e-9,vmax=100, ro=False, unit='um' )
        self.dh = self.settings.New('dh', initial=1, **lq_params)
        self.dh.spinbox_decimals = 3
        self.dv = self.settings.New('dv', initial=1, **lq_params)
        self.dv.spinbox_decimals = 3
        
        self.Nh = self.settings.New('Nh', initial=11, vmin=1, dtype=int, ro=False)
        self.Nv = self.settings.New('Nv', initial=11, vmin=1, dtype=int, ro=False)
        
        self.scan_type = self.settings.New('scan_type', dtype=str, initial='raster',
                                                  choices=('raster', 'serpentine', 'trace_retrace', 
                                                           'ortho_raster', 'ortho_trace_retrace'))

        #update Nh, Nv and other scan parameters when changes to inputs are made 
        #for lqname in 'h0 h1 v0 v1 dh dv'.split():
        #    self.logged_quantities[lqname].updated_value.connect(self.compute_scan_params)
        self.h_range = LQRange(self.h0, self.h1, self.dh, self.Nh)
        self.h_range.updated_range.connect(self.compute_scan_params)

        self.v_range = LQRange(self.v0, self.v1, self.dv, self.Nv)
        self.v_range.updated_range.connect(self.compute_scan_params) #update other scan parameters when changes to inputs are made

        self.scan_type.updated_value.connect(self.compute_scan_params)
        
        #connect events
        self.ui.start_pushButton.clicked.connect(self.start)
        self.ui.interrupt_pushButton.clicked.connect(self.interrupt)

        self.h0.connect_bidir_to_widget(self.ui.h0_doubleSpinBox)
        self.h1.connect_bidir_to_widget(self.ui.h1_doubleSpinBox)
        self.v0.connect_bidir_to_widget(self.ui.v0_doubleSpinBox)
        self.v1.connect_bidir_to_widget(self.ui.v1_doubleSpinBox)
        self.dh.connect_bidir_to_widget(self.ui.dh_doubleSpinBox)
        self.dv.connect_bidir_to_widget(self.ui.dv_doubleSpinBox)
        self.Nh.connect_bidir_to_widget(self.ui.Nh_doubleSpinBox)
        self.Nv.connect_bidir_to_widget(self.ui.Nv_doubleSpinBox)
        
        self.progress.connect_bidir_to_widget(self.ui.progress_doubleSpinBox)
        #self.progress.updated_value[str].connect(self.ui.xy_scan_progressBar.setValue)
        #self.progress.updated_value.connect(self.tree_progressBar.setValue)


        self.initial_scan_setup_plotting = False
        self.display_image_map = np.zeros((10,10), dtype=float)
        self.scan_specific_setup()

    def compute_scan_params(self):
        # Don't recompute if a scan is running!
        if self.is_measuring():
            return # maybe raise error

        self.h_array = self.h_range.array #np.arange(self.h0.val, self.h1.val, self.dh.val, dtype=float)
        self.v_array = self.v_range.array #np.arange(self.v0.val, self.v1.val, self.dv.val, dtype=float)
        
        #self.Nh.update_value(len(self.h_array))
        #self.Nv.update_value(len(self.v_array))
        
        self.range_extent = [self.h0.val, self.h1.val, self.v0.val, self.v1.val]

        self.corners =  [self.h_array[0], self.h_array[-1], self.v_array[0], self.v_array[-1]]
        
        self.imshow_extent = [self.h_array[ 0] - 0.5*self.dh.val,
                              self.h_array[-1] + 0.5*self.dh.val,
                              self.v_array[ 0] - 0.5*self.dv.val,
                              self.v_array[-1] + 0.5*self.dv.val]
                
        
        # call appropriate scan generator to create 
        getattr(self, "gen_%s_scan" % self.scan_type.val)()
        
    
    def create_empty_scan_arrays(self):
        self.scan_h_positions = np.zeros(self.Npixels, dtype=float)
        self.scan_v_positions = np.zeros(self.Npixels, dtype=float)
        self.scan_slow_move   = np.zeros(self.Npixels, dtype=bool)
        self.scan_index_array = np.zeros((self.Npixels, 3), dtype=int)

    def pre_run(self):
        # set all logged quantities read only
        for lqname in "h0 h1 v0 v1 dh dv Nh Nv".split():
            self.settings.as_dict()[lqname].change_readonly(True)
    
    def run(self):
        S = self.settings
        
        self.save_h5 = True
        
        #Hardware
        # self.apd_counter_hc = self.app.hardware_components['apd_counter']
        # self.apd_count_rate = self.apd_counter_hc.apd_count_rate
        # self.stage = self.app.hardware_components['dummy_xy_stage']

        # Data File
        # H5

        # Compute data arrays
        self.compute_scan_params()
        
        self.initial_scan_setup_plotting = True
        
        self.display_image_map = np.zeros(self.scan_shape, dtype=float)

        try:
            # h5 data file setup
            self.t0 = time.time()
            if self.save_h5:
                self.h5_file = h5_io.h5_base_file(self.app, "%i_%s.h5" % (self.t0, self.name) )
                self.h5_file.attrs['time_id'] = self.t0
                H = self.h5_meas_group = self.h5_file.create_group(self.name)        
            
                #create h5 data arrays
                H['h_array'] = self.h_array
                H['v_array'] = self.v_array
                H['range_extent'] = self.range_extent
                H['corners'] = self.corners
                H['imshow_extent'] = self.imshow_extent
                H['scan_h_positions'] = self.scan_h_positions
                H['scan_v_positions'] = self.scan_v_positions
                H['scan_slow_move'] = self.scan_slow_move
                H['scan_index_array'] = self.scan_index_array
            
            self.pre_scan_setup()
            
            # start scan
            self.pixel_i = 0
            
            self.pixel_time = np.zeros(self.scan_shape, dtype=float)
            self.pixel_time_h5 = H.create_dataset(name='pixel_time', shape=self.scan_shape, dtype=float)            
            
            self.move_position_start(self.scan_h_positions[0], self.scan_v_positions[0])
            
            for self.pixel_i in range(self.Npixels):                
                if self.interrupt_measurement_called: break
                
                i = self.pixel_i
                
                self.current_scan_index = self.scan_index_array[i]
                kk, jj, ii = self.current_scan_index
                
                h,v = self.scan_h_positions[i], self.scan_v_positions[i]
                
                if self.pixel_i == 0:
                    dh = 0
                    dv = 0
                else:
                    dh = self.scan_h_positions[i] - self.scan_h_positions[i-1] 
                    dv = self.scan_v_positions[i] - self.scan_v_positions[i-1] 
                
                if self.scan_slow_move[i]:
                    self.move_position_slow(h,v, dh, dv)
                    if self.save_h5:    
                        self.h5_file.flush() # flush data to file every slow move
                else:
                    self.move_position_fast(h,v, dh, dv)
                
                # each pixel:
                # acquire signal and save to data array
                pixel_t0 = time.time()
                self.pixel_time[kk, jj, ii] = pixel_t0
                if self.save_h5:
                    self.pixel_time_h5[kk, jj, ii] = pixel_t0
                self.collect_pixel(self.pixel_i, kk, jj, ii)
                S['progress'] = 100.0*self.pixel_i / (self.Npixels)
        finally:
            if self.save_h5 and hasattr(self, 'h5_file'):
                self.h5_file.close()
    
    def move_position_start(self, x,y):
        self.stage.x_position.update_value(x)
        self.stage.y_position.update_value(y)
    
    def move_position_slow(self, x,y, dx, dy):
        self.stage.x_position.update_value(x)
        self.stage.y_position.update_value(y)
        
    def move_position_fast(self, x,y, dx, dy):
        self.stage.x_position.update_value(x)
        self.stage.y_position.update_value(y)
    
    
    def post_run(self):
            # set all logged quantities writable
            for lqname in "h0 h1 v0 v1 dh dv Nh Nv".split():
                self.settings.as_dict()[lqname].change_readonly(False)

    def clear_qt_attr(self, attr_name):
        if hasattr(self, attr_name):
            attr = getattr(self, attr_name)
            attr.deleteLater()
            del attr
            
    def setup_figure(self):
        self.compute_scan_params()
            
        self.clear_qt_attr('graph_layout')
        self.graph_layout=pg.GraphicsLayoutWidget(border=(100,100,100))
        self.ui.plot_groupBox.layout().addWidget(self.graph_layout)
        
        self.clear_qt_attr('img_plot')
        self.img_plot = self.graph_layout.addPlot()
        self.img_item = pg.ImageItem()
        self.img_plot.addItem(self.img_item)
        self.img_plot.showGrid(x=True, y=True)
        self.img_plot.setAspectLocked(lock=True, ratio=1)

        self.hist_lut = pg.HistogramLUTItem()
        self.graph_layout.addItem(self.hist_lut)

        
        #self.clear_qt_attr('current_stage_pos_arrow')
        self.current_stage_pos_arrow = pg.ArrowItem()
        self.current_stage_pos_arrow.setZValue(100)
        self.img_plot.addItem(self.current_stage_pos_arrow)
        
        #self.stage = self.app.hardware_components['dummy_xy_stage']
        self.stage.x_position.updated_value.connect(self.update_arrow_pos, QtCore.Qt.UniqueConnection)
        self.stage.y_position.updated_value.connect(self.update_arrow_pos, QtCore.Qt.UniqueConnection)
        
        self.stage.x_position.connect_bidir_to_widget(self.ui.x_doubleSpinBox)
        self.stage.y_position.connect_bidir_to_widget(self.ui.y_doubleSpinBox)

        
        self.graph_layout.nextRow()
        self.pos_label = pg.LabelItem(justify='right')
        self.pos_label.setText("=====")
        self.graph_layout.addItem(self.pos_label)

        self.scan_roi = pg.ROI([0,0],[1,1], movable=True)
        self.scan_roi.addScaleHandle([1, 1], [0, 0])
        self.scan_roi.addScaleHandle([0, 0], [1, 1])
        self.update_scan_roi()
        self.scan_roi.sigRegionChangeFinished.connect(self.mouse_update_scan_roi)
        
        self.img_plot.addItem(self.scan_roi)        
        for lqname in 'h0 h1 v0 v1 dh dv'.split():
            self.settings.as_dict()[lqname].updated_value.connect(self.update_scan_roi)
                    
        self.img_plot.scene().sigMouseMoved.connect(self.mouseMoved)
    
    def mouse_update_scan_roi(self):
        x0,y0 =  self.scan_roi.pos()
        w, h =  self.scan_roi.size()
        print x0,y0, w, h
        self.h0.update_value(x0+self.dh.val)
        self.h1.update_value(x0+w-self.dh.val)
        self.v0.update_value(y0+self.dv.val)
        self.v1.update_value(y0+h-self.dv.val)
        self.compute_scan_params()
        self.update_scan_roi()
        
    def update_scan_roi(self):
        x0, x1, y0, y1 = self.imshow_extent
        self.scan_roi.blockSignals(True)
        self.scan_roi.setPos( (x0, y0, 0))
        self.scan_roi.setSize( (x1-x0, y1-y0, 0))
        self.scan_roi.blockSignals(False)
        
    def update_arrow_pos(self):
        x = self.stage.x_position.val
        y = self.stage.y_position.val
        self.current_stage_pos_arrow.setPos(x,y)
    
    def update_display(self):
        if self.initial_scan_setup_plotting:
            self.img_item = pg.ImageItem()
            self.img_plot.addItem(self.img_item)
            self.hist_lut.setImageItem(self.img_item)
    
            self.img_item.setImage(self.display_image_map.T)
            x0, x1, y0, y1 = self.imshow_extent
            print x0, x1, y0, y1
            self.img_item.setRect(QtCore.QRectF(x0, y0, x1-x0, y1-y0))
            
            self.initial_scan_setup_plotting = False
        else:
            #if self.settings.scan_type.val in ['raster']
            kk, jj, ii = self.current_scan_index
            self.img_item.setImage(self.display_image_map[kk,:,:].T, autoRange=False, autoLevels=False)
            self.hist_lut.imageChanged(autoLevel=True)        
    
    def mouseMoved(self,evt):
        mousePoint = self.img_plot.vb.mapSceneToView(evt)
        #print mousePoint
        
        #self.pos_label_text = "H {:+02.2f} um [{}], V {:+02.2f} um [{}]: {:1.2e} Hz ".format(
        #                mousePoint.x(), ii, mousePoint.y(), jj,
        #                self.count_rate_map[jj,ii] 
        #                )


        self.pos_label.setText(
            "H {:+02.2f} um [{}], V {:+02.2f} um [{}]: {:1.2e} Hz".format(
                        mousePoint.x(), 0, mousePoint.y(), 0, 0))

    def scan_specific_setup(self):
        "subclass this function to setup additional logged quantities and gui connections"
        self.stage = self.app.hardware.dummy_xy_stage
        
        #self.app.hardware_components['dummy_xy_stage'].x_position.connect_bidir_to_widget(self.ui.x_doubleSpinBox)
        #self.app.hardware_components['dummy_xy_stage'].y_position.connect_bidir_to_widget(self.ui.y_doubleSpinBox)
        
        #self.app.hardware_components['apd_counter'].int_time.connect_bidir_to_widget(self.ui.int_time_doubleSpinBox)
       
       
       
        # logged quantities
        # connect events
        
    
    def pre_scan_setup(self):
        print self.name, "pre_scan_setup not implemented"
        # hardware
        # create data arrays
        # update figure
    
    def collect_pixel(self, pixel_num, k, j, i):
        # collect data
        # store in arrays        
        print self.name, "collect_pixel", pixel_num, k,j,i, "not implemented"
    
    def post_scan_cleanup(self):
        print self.name, "post_scan_setup not implemented"
    
    
    
    #### Scan Generators
    def gen_raster_scan(self):
        self.Npixels = len(self.h_array)*len(self.v_array) 
        self.create_empty_scan_arrays()
        self.scan_shape = (1, self.Nv.val, self.Nh.val)
        
        pixel_i = 0
        for jj in range(self.Nv.val):
            self.scan_slow_move[pixel_i] = True
            for ii in range(self.Nh.val):
                self.scan_v_positions[pixel_i] = self.v_array[jj]
                self.scan_h_positions[pixel_i] = self.h_array[ii]
                self.scan_index_array[pixel_i,:] = [0, jj, ii] 
                pixel_i += 1
    
    def gen_serpentine_scan(self):
        self.Npixels = len(self.h_array)*len(self.v_array) 
        self.create_empty_scan_arrays()
        self.scan_shape = (1, self.Nv.val, self.Nh.val)
        
        pixel_i = 0
        for jj in range(self.Nv.val):
            self.scan_slow_move[pixel_i] = True
            
            if jj % 2: #odd lines
                h_line_indicies = range(self.Nh.val)[::-1]
            else:       #even lines -- traverse in opposite direction
                h_line_indicies = range(self.Nh.val)            
    
            for ii in h_line_indicies:            
                self.scan_v_positions[pixel_i] = self.v_array[jj]
                self.scan_h_positions[pixel_i] = self.h_array[ii]
                self.scan_index_array[pixel_i,:] = [0, jj, ii]                 
                pixel_i += 1
                
    def gen_trace_retrace_scan(self):
        self.Npixels = 2*len(self.h_array)*len(self.v_array) 
        self.create_empty_scan_arrays()
        self.scan_shape = (2, self.Nv.val, self.Nh.val)

        pixel_i = 0
        for jj in range(self.Nv.val):
            self.scan_slow_move[pixel_i] = True     
            for kk, step in [(0,1),(1,-1)]: # trace kk =0, retrace kk=1
                h_line_indicies = range(self.Nh.val)[::step]
                for ii in h_line_indicies:            
                    self.scan_v_positions[pixel_i] = self.v_array[jj]
                    self.scan_h_positions[pixel_i] = self.h_array[ii]
                    self.scan_index_array[pixel_i,:] = [kk, jj, ii]                 
                    pixel_i += 1
    
    def gen_ortho_raster_scan(self):
        self.Npixels = 2*len(self.h_array)*len(self.v_array) 
        self.create_empty_scan_arrays()
        self.scan_shape = (2, self.Nv.val, self.Nh.val)

        pixel_i = 0
        for jj in range(self.Nv.val):
            self.scan_slow_move[pixel_i] = True
            for ii in range(self.Nh.val):
                self.scan_v_positions[pixel_i] = self.v_array[jj]
                self.scan_h_positions[pixel_i] = self.h_array[ii]
                self.scan_index_array[pixel_i,:] = [0, jj, ii] 
                pixel_i += 1
        for ii in range(self.Nh.val):
            self.scan_slow_move[pixel_i] = True
            for jj in range(self.Nv.val):
                self.scan_v_positions[pixel_i] = self.v_array[jj]
                self.scan_h_positions[pixel_i] = self.h_array[ii]
                self.scan_index_array[pixel_i,:] = [1, jj, ii] 
                pixel_i += 1
    
    def gen_ortho_trace_retrace_scan(self):
        print("gen_ortho_trace_retrace_scan")
        self.Npixels = 4*len(self.h_array)*len(self.v_array) 
        self.create_empty_scan_arrays()
        self.scan_shape = (4, self.Nv.val, self.Nh.val)                        
        
        pixel_i = 0
        for jj in range(self.Nv.val):
            self.scan_slow_move[pixel_i] = True     
            for kk, step in [(0,1),(1,-1)]: # trace kk =0, retrace kk=1
                h_line_indicies = range(self.Nh.val)[::step]
                for ii in h_line_indicies:            
                    self.scan_v_positions[pixel_i] = self.v_array[jj]
                    self.scan_h_positions[pixel_i] = self.h_array[ii]
                    self.scan_index_array[pixel_i,:] = [kk, jj, ii]                 
                    pixel_i += 1
        for ii in range(self.Nh.val):
            self.scan_slow_move[pixel_i] = True     
            for kk, step in [(2,1),(3,-1)]: # trace kk =2, retrace kk=3
                v_line_indicies = range(self.Nv.val)[::step]
                for jj in v_line_indicies:            
                    self.scan_v_positions[pixel_i] = self.v_array[jj]
                    self.scan_h_positions[pixel_i] = self.h_array[ii]
                    self.scan_index_array[pixel_i,:] = [kk, jj, ii]                 
                    pixel_i += 1



class TestCartesian2DSlowScan(BaseCartesian2DSlowScan):
    name='test_cart_2d_slow_scan'
    
    def pre_scan_setup(self):
        self.test_data = self.h5_meas_group.create_dataset('test_data', self.scan_shape, dtype=float)
         
    def collect_pixel(self, pixel_i, k,j,i):
        print pixel_i, k,j,i
        px_data = np.random.rand()
        self.display_image_map[k,j,i] = px_data
        self.test_data[k,j,i] = px_data 
        time.sleep(0.01)
