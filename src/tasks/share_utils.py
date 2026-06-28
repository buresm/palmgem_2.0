import vtk
from vtk.util import numpy_support
import matplotlib.pyplot  as plt
import numpy as np
import os
from src.logger import debug, progress, verbose, warning, error, sql_debug, sql_verbose

def variable_visualization(var, x, y, var_name, par_id, text_id, path, scale=15, color_name='gist_rainbow', show_plots=False): #hsv
    """ create 2d plot from var 2d matrix"""
    # TODO: add posibility to directly add X, Y = lat, lon
    if not show_plots:
        plt.ioff()
    ny, nx = var.shape
    fig = plt.figure()
    ax = plt.subplot(111)
    X, Y = np.meshgrid(x, y)

    ax_sl = ax.imshow(var, aspect='equal', cmap=plt.get_cmap(color_name), origin='lower',
                      )
    fig.colorbar(ax_sl, extend='max', orientation = 'horizontal')

    plt.title('{}: {}\n'
              '[{}], '
              'min: {:.2f}, max: {:.2f}, avg: {:.2f}, stdev: {:.2f}'.format(
                var_name, par_id, text_id,
                np.min(var), np.max(var), np.average(var), np.std(var)))

    fig.savefig(os.path.join(path,'{}_{}.png'.format(var_name, par_id)),
                dpi=400)
    debug('{}: {} was successfully plotted', var_name, par_id)

def create_slanted_vtk(db, cfg):
    """ Generate VTK file from slanted face for Paraview visualization.

    :param db: the shared Database instance (provides execute()).
    :param cfg: the active ConfigObj.
    """
    progress('Processing faces into vtk - Paraview file')

    num_faces = db.execute(
        'SELECT COUNT(*) FROM "{0}"."{1}"'.format(cfg.domain.case_schema, cfg.tables.slanted_faces))[0][0]

    num_vert = db.execute(
        'SELECT COUNT(*) FROM "{0}"."{1}"'.format(cfg.domain.case_schema, cfg.tables.vertices))[0][0]

    empty_vert = cfg.slanted_pars.empty_vert
    num_faces_vert = 7
    faces = np.zeros((num_faces_vert, num_faces))
    vertices = np.zeros((3, num_vert))
    sqltext = 'SELECT vert1i, vert2i, vert3i, vert4i, vert5i, vert6i, vert7i, n_vert,' \
              '       CASE WHEN isroof THEN 0  WHEN iswall THEN 1 WHEN isterr THEN 2 ELSE 3 END, ' \
              '       CASE WHEN iswall THEN lw.type ' \
              '            WHEN isroof THEN lr.type ' \
              '            WHEN isterr THEN l.type ' \
              '            ELSE NULL END,' \
              '       CASE WHEN iswall THEN lw.lid ' \
              '            WHEN isroof THEN lr.lid ' \
              '            WHEN isterr THEN l.lid ' \
              '            ELSE NULL END ' \
              'FROM "{0}"."{1}" AS s ' \
              'LEFT OUTER JOIN "{0}"."{2}" AS l  ON l.lid  = s.lid ' \
              'LEFT OUTER JOIN "{0}"."{3}" AS w  ON w.wid  = s.wid ' \
              'LEFT OUTER JOIN "{0}"."{2}" AS lw ON lw.lid = w.lid ' \
              'LEFT OUTER JOIN "{0}"."{4}" AS r  ON r.rid  = s.rid ' \
              'LEFT OUTER JOIN "{0}"."{2}" AS lr ON lr.lid = r.lid ' \
              'ORDER BY k, j, i' \
        .format(cfg.domain.case_schema, cfg.tables.slanted_faces, cfg.tables.landcover,
                cfg.tables.walls, cfg.tables.roofs)
    vert_points = db.execute(sqltext)

    for i in range(num_faces_vert):
        faces[i, :] = [empty_vert if x[i] is None else x[i] for x in
                       vert_points]  # empty_vert is for missing points
    num_verti = np.asarray([x[7] for x in vert_points])
    face_type = np.asarray([x[8] for x in vert_points])
    face_pids_type = np.asarray([x[9] for x in vert_points])
    face_lid_index = np.asarray([x[10] for x in vert_points])

    sqltext = 'SELECT ST_X(point), ST_Y(point), ST_Z(point) FROM "{0}"."{1}" ' \
              'ORDER BY id'.format(cfg.domain.case_schema, cfg.tables.vertices)
    vert_points = db.execute(sqltext)

    vertices[0, :] = [x[0] for x in vert_points]
    vertices[1, :] = [x[1] for x in vert_points]
    vertices[0, :] += - cfg.domain.origin_x
    vertices[1, :] += - cfg.domain.origin_y
    vertices[2, :] = [x[2] for x in vert_points]
    del vert_points

    cells = vtk.vtkCellArray()
    qp = vtk.vtkPoints()
    qp.SetDataTypeToDouble()
    # qp.SetNumberOfPoints(num_vert)
    pid = np.zeros(num_vert).astype('int')
    for i in range(num_vert):
        pid[i] = qp.InsertNextPoint(np.array([vertices[0, i], vertices[1, i], vertices[2, i]]))

    for i in range(num_faces):
        # print(faces[i, :num_verti[i]])
        # FIXME that (-1) is because postgis has ids from 1 to num_vert, but python start from 0.
        pol = vtk.vtkPolygon()
        if num_verti[i] < 3:
            continue
        pol.GetPointIds().SetNumberOfIds(num_verti[i]+1)
        pol.GetPointIds().SetId(0, int(faces[0, i]) - 1)
        pol.GetPointIds().SetId(1, int(faces[1, i]) - 1)
        pol.GetPointIds().SetId(2, int(faces[2, i]) - 1)
        if num_verti[i] > 3:
            pol.GetPointIds().SetId(3, int(faces[3, i]) - 1)
        else:
            pol.GetPointIds().SetId(3, int(faces[0, i]) - 1)
            cells.InsertNextCell(pol)

            continue
        if num_verti[i] > 4:
            pol.GetPointIds().SetId(4, int(faces[4, i]) - 1)
        else:
            pol.GetPointIds().SetId(4, int(faces[0, i]) - 1)
            cells.InsertNextCell(pol)
            continue

        if num_verti[i] > 5:
            pol.GetPointIds().SetId(5, int(faces[5, i]) - 1)
        else:
            pol.GetPointIds().SetId(5, int(faces[0, i]) - 1)
            cells.InsertNextCell(pol)
            continue

        if num_verti[i] > 6:
            pol.GetPointIds().SetId(6, int(faces[6, i]) - 1)
        else:
            pol.GetPointIds().SetId(6, int(faces[0, i]) - 1)
            cells.InsertNextCell(pol)
            continue

        if num_verti[i] > 7:
            pol.GetPointIds().SetId(7, int(faces[7, i]) - 1)
        else:
            pol.GetPointIds().SetId(7, int(faces[0, i]) - 1)
            cells.InsertNextCell(pol)
            continue


    polydata = vtk.vtkPolyData()
    polydata.SetPoints(qp)
    polydata.SetPolys(cells)

    slanted_data = np.asarray(face_type)
    VTK_data = numpy_support.numpy_to_vtk(num_array=slanted_data, deep=True, array_type=vtk.VTK_FLOAT)
    # polydata.CellData.append(data, data_name)
    polydata.GetCellData().SetScalars(VTK_data)

    writer = vtk.vtkXMLPolyDataWriter()
    writer.SetFileName(os.path.join(cfg.visual_check.path, 'slanted_faces_type.vtu'))
    writer.SetInputData(polydata)
    writer.Write()

    slanted_data = np.asarray(face_pids_type)
    VTK_data = numpy_support.numpy_to_vtk(num_array=slanted_data, deep=True, array_type=vtk.VTK_FLOAT)
    # polydata.CellData.append(data, data_name)
    polydata.GetCellData().SetScalars(VTK_data)

    writer = vtk.vtkXMLPolyDataWriter()
    writer.SetFileName(os.path.join(cfg.visual_check.path, 'slanted_faces_pids_type.vtu'))
    writer.SetInputData(polydata)
    writer.Write()

    slanted_data = np.asarray(face_lid_index)
    VTK_data = numpy_support.numpy_to_vtk(num_array=slanted_data, deep=True, array_type=vtk.VTK_FLOAT)
    # polydata.CellData.append(data, data_name)
    polydata.GetCellData().SetScalars(VTK_data)

    writer = vtk.vtkXMLPolyDataWriter()
    writer.SetFileName(os.path.join(cfg.visual_check.path, 'slanted_faces_lid_index.vtu'))
    writer.SetInputData(polydata)
    writer.Write()