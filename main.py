"""
主入口脚本：把整个后处理管线串联起来

用法示例（Windows cmd）:
    python main.py --in_raster edge_prob.tif --mask cropland_mask.tif --workdir ./out --steps thinning,vectorize,smooth,filter

支持参数：
- --steps: 指定按逗号分隔的阶段, 可选值: thinning, vectorize, smooth, filter
- --dry-run: 仅打印将运行的命令，不实际执行
- --verbose: 更详细的日志

实现说明：优先尝试以模块导入方式调用脚本（如果脚本提供函数或 main），若不可用则使用 subprocess 以独立进程运行脚本文件。
"""

import argparse
import subprocess
import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCRIPTS = {
    'thinning': ROOT / 'thinning.py',
    'smooth': ROOT / 'smooth.py',
    'filter': ROOT / 'filter_by_cropland.py',
}


def run_command(cmd, dry_run=False, verbose=False):
    if dry_run or verbose:
        print("[CMD] ", " ".join(cmd))
    if dry_run:
        return 0
    proc = subprocess.run(cmd, shell=False)
    return proc.returncode


def call_script(script_path: Path, args: list, dry_run=False, verbose=False):
    # 尝试以 python -m 脚本方式调用，保持与脚本自身运行时行为一致
    cmd = [sys.executable, str(script_path)] + args
    return run_command(cmd, dry_run=dry_run, verbose=verbose)



def main():
    p = argparse.ArgumentParser(description='Cropplot post-processing pipeline entry')
    p.add_argument('--in_raster', help='输入边缘概率图（GeoTIFF）', default='edge_map')
    p.add_argument('--out_dir', help='输出目录', default='out_dir')
    p.add_argument('--mask', help='耕地掩膜（Mask TIF），filter 阶段需要', default='cropland')
    p.add_argument('--keep', action='store_true', help='是否保留中间结果（thinning/smooth），默认不保留')
    p.add_argument('--step', choices=['thinning', 'smooth', 'filter'], help='只运行单个阶段并退出')
    p.add_argument('--dry-run', action='store_true', help='只打印命令不执行')
    p.add_argument('--verbose', action='store_true', help='打印详细信息')

    # 额外通用参数，可传递给每个脚本（简单起见，作为未解析的字符串传下去）
    p.add_argument('--extra', help='额外参数，传递给每个脚本（示例: "--opt 1 --flag"）', default='')

    args = p.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 支持 --in_raster 指向单个文件或目录
    in_path = Path(args.in_raster)
    # 如果是文件夹，则收集所有 tif 文件（不递归）
    if in_path.is_dir():
        rasters = sorted([p for p in in_path.iterdir() if p.suffix.lower() in ['.tif', '.tiff']])
        if not rasters:
            print(f'No tif files found in input directory: {in_path}')
            sys.exit(2)
    else:
        rasters = [in_path]

    # 支持 mask 为文件或目录。当为目录时，按相同 basename 去匹配掩膜文件
    mask_path = Path(args.mask) if args.mask else None

    def get_mask_for(raster: Path):
        if not mask_path:
            return None
        if mask_path.is_dir():
            # 在 mask 目录中查找与 raster 同名的 tif 文件
            candidate = mask_path / raster.name
            if candidate.exists():
                return str(candidate)
            # 也尝试仅替换扩展名为 .tif
            candidate2 = mask_path / (raster.stem + '.tif')
            if candidate2.exists():
                return str(candidate2)
            return None
        else:
            return str(mask_path)

    # helper: 根据 raster 名称生成输出 shapefile 路径
    def outputs_for(raster: Path):
        base = raster.stem
        thinning_out = out_dir / f'{base}_origin.shp'
        smooth_out = out_dir / f'{base}_smooth.shp'
        filter_out = out_dir / f'{base}.shp'
        return thinning_out, smooth_out, filter_out

    # 尝试导入 tqdm，用于显示进度条；若不可用，回退到普通迭代
    try:
        from tqdm.auto import tqdm
    except Exception:
        tqdm = None

    # If user requests a single step, run that for each raster and exit
    if args.step:
        step = args.step
        iterator = tqdm(rasters, desc=f'Processing ({step})') if tqdm else rasters
        for raster in iterator:
            thinning_out, smooth_out, filter_out = outputs_for(raster)
            # get mask for this raster (may be None)
            mask_for_raster = get_mask_for(raster)

            if step == 'thinning':
                script = SCRIPTS['thinning']
                cmd_args = ['--in_raster', str(raster), '--out_shp', str(thinning_out)]
                if args.extra:
                    cmd_args += args.extra.split()
                print(f"\n=== Running thinning (single-step) for {raster.name} ===")
                rc = call_script(script, cmd_args, dry_run=args.dry_run, verbose=args.verbose)
                if rc != 0:
                    print('thinning failed with code', rc)
                    sys.exit(rc)
                print('Finished thinning (single-step). Output:', thinning_out)
                continue

            if step == 'smooth':
                # require input shapefile to exist
                if not os.path.exists(thinning_out) and not args.dry_run:
                    print(f'smooth requires thinning output {thinning_out} to exist')
                    sys.exit(2)
                script = SCRIPTS['smooth']
                cmd_args = ['--input_shp', str(thinning_out), '--output_shp', str(smooth_out)]
                if args.extra:
                    cmd_args += args.extra.split()
                print(f"\n=== Running smooth (single-step) for {raster.name} ===")
                rc = call_script(script, cmd_args, dry_run=args.dry_run, verbose=args.verbose)
                if rc != 0:
                    print('smooth failed with code', rc)
                    sys.exit(rc)
                print('Finished smooth (single-step). Output:', smooth_out)
                continue

            if step == 'filter':
                if not mask_for_raster:
                    print(f'filter step needs --mask argument or matching mask for {raster.name}')
                    sys.exit(2)
                if not os.path.exists(smooth_out) and not args.dry_run:
                    print(f'filter requires smooth output {smooth_out} to exist')
                    sys.exit(2)
                script = SCRIPTS['filter']
                cmd_args = ['--parcel_shp', str(smooth_out), '--mask_tif', mask_for_raster, '--output_shp', str(filter_out)]
                if args.extra:
                    cmd_args += args.extra.split()
                print(f"\n=== Running filter (single-step) for {raster.name} ===")
                rc = call_script(script, cmd_args, dry_run=args.dry_run, verbose=args.verbose)
                if rc != 0:
                    print('filter failed with code', rc)
                    sys.exit(rc)
                print('Finished filter (single-step). Output:', filter_out)
                continue
        return

    # 固定顺序运行：对每个 raster 执行 thinning -> smooth -> filter
    iterator = tqdm(rasters, desc='Processing (full)') if tqdm else rasters
    for raster in iterator:
        thinning_out, smooth_out, filter_out = outputs_for(raster)
        mask_for_raster = get_mask_for(raster)

        # 1) thinning
        script = SCRIPTS['thinning']
        cmd_args = ['--in_raster', str(raster), '--out_shp', str(thinning_out)]
        if args.extra:
            cmd_args += args.extra.split()
        print(f"\n=== Running thinning for {raster.name} ===")
        rc = call_script(script, cmd_args, dry_run=args.dry_run, verbose=args.verbose)
        if rc != 0:
            print('thinning failed with code', rc)
            sys.exit(rc)

        # 2) smooth
        script = SCRIPTS['smooth']
        cmd_args = ['--input_shp', str(thinning_out), '--output_shp', str(smooth_out)]
        if args.extra:
            cmd_args += args.extra.split()
        print(f"\n=== Running smooth for {raster.name} ===")
        rc = call_script(script, cmd_args, dry_run=args.dry_run, verbose=args.verbose)
        if rc != 0:
            print('smooth failed with code', rc)
            sys.exit(rc)

        # 3) filter
        if not mask_for_raster:
            print(f'filter step needs --mask argument or matching mask for {raster.name}')
            sys.exit(2)
        script = SCRIPTS['filter']
        cmd_args = ['--parcel_shp', str(smooth_out), '--mask_tif', mask_for_raster, '--output_shp', str(filter_out)]
        if args.extra:
            cmd_args += args.extra.split()
        print(f"\n=== Running filter for {raster.name} ===")
        rc = call_script(script, cmd_args, dry_run=args.dry_run, verbose=args.verbose)
        if rc != 0:
            print('filter failed with code', rc)
            sys.exit(rc)

    # 清理中间结果（如用户没有选择保留）
    if not args.keep and not args.dry_run:
        def remove_shapefile(base_path: Path):
            # 删除 .shp/.shx/.dbf/.prj 等相关文件
            patterns = [str(base_path) + ext for ext in ['.shp', '.shx', '.dbf', '.prj', '.cpg']]
            for p in patterns:
                try:
                    if os.path.exists(p):
                        os.remove(p)
                except Exception:
                    pass

        # 对于所有 rasters，删除中间 shapefile
        for raster in rasters:
            thinning_out, smooth_out, filter_out = outputs_for(raster)
            try:
                remove_shapefile(thinning_out.with_suffix(''))
                remove_shapefile(smooth_out.with_suffix(''))
                thinning_out_tif = thinning_out.with_suffix('.tif')
                if thinning_out_tif.exists():
                    thinning_out_tif.unlink()
            except Exception:
                pass

    print('\nPipeline finished successfully. Outputs:', filter_out)


if __name__ == '__main__':
    main()
